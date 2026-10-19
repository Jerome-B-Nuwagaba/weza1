"""Product Studio (FSD §18–19; TSD §16). Every change is a new version; maker-checker approval;
AI extraction only ever produces DRAFTs (BR-004, Skill §26)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.matching.rules import OPS, ruleset_hash
from weza.domains.product.models import Product, ProductVersion
from weza.domains.trust import policy
from weza.domains.trust.service import audit
from weza.platform.context import Actor
from weza.platform.db import utcnow
from weza.platform.errors import NotFound, ValidationFailed
from weza.platform.events import emit

RULE_FIELDS = {"amount", "tenor_months", "customer_type", "sector", "district", "region", "purpose_category",
               "business_age_months", "monthly_turnover", "business_registered", "employment_type", "employment_months",
               "monthly_income", "farm_activity", "operating_months", "annual_income", "monthly_repayments",
               "debt_service_ratio", "has_nin"}
FAMILIES = {"SME_WORKING_CAPITAL": "SME working capital", "SME_GROWTH": "SME growth / expansion",
            "ASSET_FINANCE": "Asset & equipment finance", "SALARY_LOAN": "Salary loan", "SCHOOL_FEES": "School fees",
            "AGRI_INPUTS": "Agricultural inputs", "AGRI_ASSET": "Agricultural assets", "PERSONAL": "Personal loan"}


def validate_payload(p: dict) -> dict:
    terms = p.get("terms") or {}
    try:
        lo, hi = float(terms.get("min_amount", 0)), float(terms.get("max_amount", 0))
    except (TypeError, ValueError) as exc:
        raise ValidationFailed("Amounts must be numbers.") from exc
    if lo <= 0 or hi <= 0 or lo > hi:
        raise ValidationFailed("Set a valid minimum and maximum amount.", details=[{"field": "terms.min_amount"}])
    tlo, thi = int(terms.get("min_tenor_months") or 1), int(terms.get("max_tenor_months") or 12)
    if tlo < 1 or tlo > thi:
        raise ValidationFailed("Set a valid tenor range.", details=[{"field": "terms.min_tenor_months"}])
    if p.get("family") not in FAMILIES:
        raise ValidationFailed("Choose a product family.", details=[{"field": "family"}])
    rules = []
    for r in p.get("rules") or []:
        if r.get("field") not in RULE_FIELDS or r.get("op") not in OPS:
            raise ValidationFailed(f"Unsupported rule: {r.get('field')} {r.get('op')}.")
        rules.append({k: r[k] for k in ("field", "op", "value", "label") if k in r})
    reqs = [{"doc_type": d["doc_type"], "label": d.get("label") or d["doc_type"].replace("_", " ").title(),
             "required": bool(d.get("required"))} for d in (p.get("requirements") or [])]
    return {"name": p["name"].strip()[:160], "family": p["family"], "rules": rules, "requirements": reqs,
            "terms": {**terms, "min_amount": lo, "max_amount": hi, "min_tenor_months": tlo, "max_tenor_months": thi}}


def create(db: Session, actor: Actor, payload: dict, provenance: dict | None = None) -> ProductVersion:
    policy.require(actor, "product.create")
    v = validate_payload(payload)
    prod = Product(institution_id=actor.institution_id, name=v["name"], family=v["family"], status="DRAFT")
    db.add(prod)
    db.flush()
    pv = ProductVersion(product_id=prod.id, institution_id=prod.institution_id, version=1, status="DRAFT",
                        author_id=actor.id, provenance=provenance, **v)
    pv.ruleset_hash = ruleset_hash(pv.rules, pv.terms)
    db.add(pv)
    db.flush()
    audit(db, actor, "product.created", "product", prod.id, after={"version": 1, "ai_draft": bool(provenance)})
    return pv


def new_version(db: Session, actor: Actor, prod: Product, payload: dict) -> ProductVersion:
    policy.require(actor, "product.create")
    policy.require_tenant(actor, prod.institution_id)
    v = validate_payload(payload)
    draft = db.execute(select(ProductVersion).where(ProductVersion.product_id == prod.id,
                                                    ProductVersion.status.in_(["DRAFT", "PENDING_APPROVAL"]))).scalar_one_or_none()
    if draft is not None:
        if draft.status == "PENDING_APPROVAL":
            raise ValidationFailed("A version is awaiting approval. Approve or reject it first.")
        for k, val in v.items():
            setattr(draft, k, val)
        draft.author_id = actor.id
        draft.ruleset_hash = ruleset_hash(draft.rules, draft.terms)
        return draft
    n = db.execute(select(func.max(ProductVersion.version)).where(ProductVersion.product_id == prod.id)).scalar_one() or 0
    pv = ProductVersion(product_id=prod.id, institution_id=prod.institution_id, version=n + 1, status="DRAFT",
                        author_id=actor.id, **v)
    pv.ruleset_hash = ruleset_hash(pv.rules, pv.terms)
    db.add(pv)
    db.flush()
    audit(db, actor, "product.version_drafted", "product", prod.id, after={"version": pv.version})
    return pv


def submit(db: Session, actor: Actor, pv: ProductVersion) -> None:
    policy.require(actor, "product.create")
    policy.require_tenant(actor, pv.institution_id)
    if pv.status != "DRAFT":
        raise ValidationFailed("Only drafts can be submitted.")
    pv.status, pv.submitted_at = "PENDING_APPROVAL", utcnow()
    prod = db.get(Product, pv.product_id)
    if prod.status == "DRAFT":
        prod.status = "PENDING_APPROVAL"
    audit(db, actor, "product.submitted", "product", pv.product_id, after={"version": pv.version})
    emit(db, "ProductSubmitted", topic="institution", aggregate_type="product", aggregate_id=pv.product_id,
         institution_id=pv.institution_id, data={"version": pv.version, "name": pv.name})


def review(db: Session, actor: Actor, pv: ProductVersion, approve: bool, note: str | None) -> None:
    """HUMAN_APPROVE_PRODUCT_CONFIGURATION — maker-checker: the author cannot approve their own version."""
    policy.require(actor, "product.approve")
    policy.require_tenant(actor, pv.institution_id)
    if pv.status != "PENDING_APPROVAL":
        raise ValidationFailed("This version is not awaiting approval.")
    if pv.author_id == actor.id:
        raise ValidationFailed("Maker-checker: someone other than the author must approve.", code="MAKER_CHECKER")
    prod = db.get(Product, pv.product_id)
    pv.review_note = note
    if not approve:
        pv.status = "REJECTED"
        if prod.status == "PENDING_APPROVAL" and prod.active_version_id is None:
            prod.status = "DRAFT"
        audit(db, actor, "product.rejected", "product", prod.id, after={"version": pv.version}, reason=note)
        return
    now = utcnow()
    if prod.active_version_id:
        old = db.get(ProductVersion, prod.active_version_id)
        old.status, old.effective_to = "SUPERSEDED", now
    pv.status, pv.approver_id, pv.approved_at, pv.effective_from = "APPROVED", actor.id, now, now
    prod.active_version_id, prod.name, prod.family = pv.id, pv.name, pv.family
    prev_status = prod.status
    if prod.status in ("DRAFT", "PENDING_APPROVAL"):
        prod.status = "ACTIVE"
    audit(db, actor, "product.approved", "product", prod.id, before={"status": prev_status},
          after={"version": pv.version, "ruleset_hash": pv.ruleset_hash}, reason=note)
    emit(db, "ProductActivated", topic="institution", aggregate_type="product", aggregate_id=prod.id,
         institution_id=prod.institution_id, data={"version": pv.version})


def set_status(db: Session, actor: Actor, prod: Product, to: str, reason: str) -> None:
    if not actor.is_weza:
        policy.require(actor, "product.approve")
        policy.require_tenant(actor, prod.institution_id)
    allowed = {"ACTIVE": {"PAUSED", "ARCHIVED"}, "PAUSED": {"ACTIVE", "ARCHIVED"}}
    if to not in allowed.get(prod.status, set()):
        raise ValidationFailed(f"Product cannot move from {prod.status} to {to}.", code="INVALID_TRANSITION")
    before, prod.status = prod.status, to
    audit(db, actor, f"product.{to.lower()}", "product", prod.id, before={"status": before}, after={"status": to},
          reason=reason)
    emit(db, "ProductActivated" if to == "ACTIVE" else "ProductPaused", topic="institution", aggregate_type="product",
         aggregate_id=prod.id, institution_id=prod.institution_id, data={"status": to})


def get_owned(db: Session, actor: Actor, product_id: uuid.UUID) -> Product:
    query = select(Product).where(Product.id == product_id)
    if not actor.is_weza:
        query = query.where(Product.institution_id == actor.institution_id)
    prod = db.execute(query).scalar_one_or_none()
    if prod is None:
        raise NotFound("Not found.")
    policy.require_tenant(actor, prod.institution_id)
    return prod
