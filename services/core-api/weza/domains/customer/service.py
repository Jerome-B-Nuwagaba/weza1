"""Customer profile service: provenance-tracked facts, conflict detection, immutable snapshots,
rule-field projection and the WEZA Quality Score (FSD §8–9, TSD §11, §14; Skill §18–19)."""

import json
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.admin_config import get_config, region_of
from weza.domains.customer.models import Customer, Document, Fact, Preference, ProfileSnapshot
from weza.domains.identity import service as identity
from weza.platform.crypto import sha256_hex
from weza.platform.db import utcnow
from weza.platform.events import emit

# Facts whose change makes existing matches stale (Skill §19–21)
MATERIAL_KEYS = {
    "business.sector", "business.district", "business.age_months", "business.monthly_turnover", "business.registered",
    "employment.type", "employment.months", "employment.monthly_net_income", "residence.district", "farm.activity",
    "farm.district", "farm.operating_months", "farm.annual_income", "finance.monthly_repayments", "need.tenor_months",
}
FACT_FRESH_DAYS = 180

VAULT_KEYS = {"identity.full_name": "full_name", "identity.nin": "nin", "identity.email": "email"}

FIELD_LABELS = {
    "identity.full_name_captured": "Full name", "identity.nin_captured": "National ID (NIN)",
    "business.name": "Business name", "business.sector": "Sector", "business.district": "Business district",
    "business.age_months": "Business age", "business.monthly_turnover": "Monthly turnover",
    "business.registered": "Business registered", "finance.monthly_repayments": "Existing monthly repayments",
    "need.tenor_months": "Preferred repayment period", "employment.employer": "Employer",
    "employment.type": "Employment type", "employment.months": "Time with employer",
    "employment.monthly_net_income": "Monthly take-home pay", "residence.district": "District",
    "farm.activity": "Farming activity", "farm.district": "Farm district", "farm.operating_months": "Farming for",
    "farm.annual_income": "Annual farm income",
}
# Profile fields a customer can set themselves (directly or by answering an institution's question)
EDITABLE = {k for k in FIELD_LABELS if not k.endswith("_captured")}


def parse_fact_value(key: str, raw: str):
    """Parse a customer's typed answer for a profile field exactly as the conversation does.
    Returns (value, None) or (None, help text)."""
    from weza.domains.admin_config import QUESTION_PATHS
    from weza.domains.need import journey
    q = next((q for path in QUESTION_PATHS.values() for q in path if q["key"] == key), None)
    if q is None:
        return raw, None
    value = journey._parse_answer(q, str(raw))
    return (value, None) if value is not None else (None, journey._help_for(q))


def get_or_create_by_phone(db: Session, phone_e164: str, *, attribution_id=None, device_hash: str | None = None,
                           is_demo: bool = False) -> tuple[Customer, bool]:
    rec = identity.vault_find_by_phone(db, phone_e164)
    if rec:
        cust = db.execute(select(Customer).where(Customer.vault_token == rec.id)).scalar_one()
        cust.last_activity_at = utcnow()
        return cust, False
    rec = identity.vault_create(db, phone_e164)
    cust = Customer(vault_token=rec.id, attribution_id=attribution_id, device_hash=device_hash, is_demo=is_demo)
    db.add(cust)
    db.flush()
    db.add(Preference(customer_id=cust.id, ranking=[]))
    emit(db, "CustomerVerified", topic="customer", aggregate_type="customer", aggregate_id=cust.id,
         data={"new": True})
    return cust, True


def current_facts(db: Session, customer_id: uuid.UUID) -> dict[str, Fact]:
    rows = db.execute(select(Fact).where(Fact.customer_id == customer_id, Fact.superseded_at.is_(None))).scalars()
    return {f.key: f for f in rows}


def fact_values(db: Session, customer_id: uuid.UUID) -> dict:
    return {k: f.value.get("v") for k, f in current_facts(db, customer_id).items()}


def _same(a, b) -> bool:
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except Exception:  # noqa: BLE001
        return str(a).strip().lower() == str(b).strip().lower()


def _norm(v) -> str:
    return str(v or "").strip().upper()


def upsert_fact(db: Session, customer_id: uuid.UUID, key: str, value, *, source: str = "CUSTOMER",
                channel: str = "web", confidence: float | None = None, confirmed: bool = False,
                source_ref: str | None = None) -> tuple[Fact | None, Fact | None]:
    """Record a fact. Returns (new_fact, conflicting_fact). A conflict is returned (and nothing written) when an
    existing confirmed value from a *different* source disagrees — WEZA never silently picks one (Skill §19)."""
    if key in VAULT_KEYS:
        cust = db.get(Customer, customer_id)
        before = identity.vault_read(db, cust.vault_token)
        identity.vault_update(db, cust.vault_token, **{VAULT_KEYS[key]: value})
        # A typed NIN is only a claim: identity is verified against the registry asynchronously
        # (IdentityCaptured → identity_verify consumer). A changed NIN or name needs a fresh check.
        changed = value and _norm(before.get(VAULT_KEYS[key])) != _norm(value)
        nin_known = key == "identity.nin" or before.get("nin")
        if key in ("identity.nin", "identity.full_name") and changed and nin_known:
            if cust.verification_level == "IDENTITY":
                cust.verification_level = "PHONE"
            from weza.domains.verification.service import request_check
            check = request_check(db, cust)  # PENDING until the registry answers
            emit(db, "IdentityCaptured", topic="customer", aggregate_type="customer", aggregate_id=customer_id,
                 data={"changed": key, "check_id": str(check.id)})
        key, value = key + "_captured", bool(value)
    existing = current_facts(db, customer_id).get(key)
    now = utcnow()
    if existing is not None:
        if _same(existing.value.get("v"), value):
            if confirmed and existing.verification_state not in ("CONFIRMED", "VERIFIED"):
                existing.verification_state = "CONFIRMED"
                existing.confirmed_at = now
            existing.fresh_until = now + timedelta(days=FACT_FRESH_DAYS)
            return existing, None
        if (existing.source != source and existing.verification_state in ("CONFIRMED", "VERIFIED")
                and not confirmed):
            return None, existing
        existing.superseded_at = now
    fact = Fact(customer_id=customer_id, key=key, value={"v": value}, source=source, source_channel=channel,
                source_ref=source_ref, confidence=confidence,
                verification_state="CONFIRMED" if confirmed else ("EXTRACTED" if source == "AI_EXTRACTED" else "SELF_REPORTED"),
                captured_at=now, confirmed_at=now if confirmed else None,
                fresh_until=now + timedelta(days=FACT_FRESH_DAYS))
    db.add(fact)
    db.flush()
    if existing is not None and key in MATERIAL_KEYS:
        emit(db, "MaterialFactChanged", topic="customer", aggregate_type="customer", aggregate_id=customer_id,
             data={"key": key})
    return fact, None


def is_fresh(f: Fact) -> bool:
    return f.fresh_until is None or f.fresh_until > utcnow()


def snapshot_profile(db: Session, customer_id: uuid.UUID) -> ProfileSnapshot:
    facts = {k: {"v": f.value.get("v"), "source": f.source, "state": f.verification_state,
                 "captured_at": f.captured_at.isoformat()} for k, f in current_facts(db, customer_id).items()}
    h = sha256_hex(json.dumps({k: v["v"] for k, v in facts.items()}, sort_keys=True, default=str))
    last = db.execute(select(ProfileSnapshot).where(ProfileSnapshot.customer_id == customer_id)
                      .order_by(ProfileSnapshot.version.desc()).limit(1)).scalar_one_or_none()
    if last and last.hash == h:
        return last
    snap = ProfileSnapshot(customer_id=customer_id, version=(last.version + 1) if last else 1, facts=facts, hash=h)
    db.add(snap)
    db.flush()
    return snap


def documents_on_file(db: Session, customer_id: uuid.UUID) -> set[str]:
    rows = db.execute(select(Document.doc_type).where(Document.customer_id == customer_id,
                                                      Document.pipeline_state.in_(["STORED", "CONFIRMED"]))).scalars()
    return set(rows)


def rule_fields(need, facts: dict, docs: set[str] | None = None, customer: Customer | None = None) -> dict:
    """Project need + profile facts into the deterministic rule-field catalogue (blueprint 04 §4)."""
    f = facts
    district = f.get("business.district") or f.get("residence.district") or f.get("farm.district") or need.district
    income = f.get("employment.monthly_net_income")
    turnover = f.get("business.monthly_turnover")
    annual = f.get("farm.annual_income")
    monthly_capacity = income or (Decimal(str(turnover)) * Decimal("0.25") if turnover else None) or \
        (Decimal(str(annual)) / 12 if annual else None)
    repayments = f.get("finance.monthly_repayments")
    dsr = None
    if monthly_capacity and repayments is not None and Decimal(str(monthly_capacity)) > 0:
        dsr = float(Decimal(str(repayments)) / Decimal(str(monthly_capacity)))
    return {
        "amount": float(need.amount) if need.amount is not None else None,
        "tenor_months": f.get("need.tenor_months") or need.tenor_months,
        "customer_type": need.customer_type,
        "sector": f.get("business.sector") or need.sector or ("agriculture" if need.customer_type == "AGRICULTURE" else None),
        "district": district,
        "region": region_of(district),
        "purpose_category": need.purpose_category,
        "business_age_months": f.get("business.age_months"),
        "monthly_turnover": float(turnover) if turnover is not None else None,
        "business_registered": f.get("business.registered"),
        "employment_type": f.get("employment.type"),
        "employment_months": f.get("employment.months"),
        "monthly_income": float(income) if income is not None else None,
        "farm_activity": f.get("farm.activity"),
        "operating_months": f.get("farm.operating_months") or f.get("business.age_months") or f.get("employment.months"),
        "annual_income": float(annual) if annual is not None else None,
        "monthly_repayments": float(repayments) if repayments is not None else None,
        "debt_service_ratio": round(dsr, 3) if dsr is not None else None,
        "has_nin": bool(f.get("identity.nin_captured")),
        "phone_verified": customer is not None,
        "documents": sorted(docs or []),
    }


def missing_questions(db: Session, need, customer_id: uuid.UUID | None, country: str = "UG") -> list[dict]:
    paths, _ = get_config(db, f"question_paths:{country}")
    path = paths.get(need.customer_type or "", [])
    facts = current_facts(db, customer_id) if customer_id else {}
    out = []
    for q in path:
        key = q["key"]
        stored = facts.get(key) or facts.get(key + "_captured")
        if key == "business.sector" and (need.sector and not stored):
            continue  # already known from the intent (confirmed with the customer)
        if stored is not None and is_fresh(stored):
            continue
        out.append(q)
    return out


def quality_score(db: Session, need, customer: Customer | None, docs_required: int = 0, docs_present: int = 0,
                  ) -> tuple[int, dict]:
    """WEZA Quality Score — marketplace completeness/readiness, NOT creditworthiness (FSD-SCR-001)."""
    w, version = get_config(db, "quality_weights")
    facts = current_facts(db, customer.id) if customer else {}
    paths, _ = get_config(db, "question_paths:UG")
    required = [q["key"] for q in paths.get(need.customer_type or "", []) if q.get("required")]
    have = sum(1 for k in required if (k in facts or k + "_captured" in facts))
    completeness = have / len(required) if required else 0.0
    conflicts = sum(1 for f in facts.values() if f.verification_state == "CONFLICTED")
    factors = {
        "phone_verified": w["phone_verified"] if customer else 0,
        "identity_captured": w["identity_captured"] if facts.get("identity.nin_captured") else
        (w["identity_captured"] // 2 if facts.get("identity.full_name_captured") else 0),
        "profile_complete": round(w["profile_complete"] * completeness),
        "documents": round(w["documents"] * (docs_present / docs_required)) if docs_required else w["documents"],
        "consistency": w["consistency"] if conflicts == 0 else 0,
        "responsiveness": w["responsiveness"] if need.intent_confirmed_at else w["responsiveness"] // 2,
    }
    return min(100, sum(factors.values())), {"factors": factors, "version": f"quality_v{version}",
                                             "note": "Marketplace readiness, not a credit score."}


def recent_need_count(db: Session, customer_id: uuid.UUID, days: int = 7) -> int:
    from weza.domains.need.models import FinancialNeed
    return db.execute(select(func.count()).select_from(FinancialNeed).where(
        FinancialNeed.customer_id == customer_id, FinancialNeed.created_at >= utcnow() - timedelta(days=days))).scalar_one()
