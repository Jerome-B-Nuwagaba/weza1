"""Appetite Studio & capital mandates (FSD §20, TSD §17, §24, §37). Simulation is mandatory before approval;
approval is human (HUMAN_APPROVE_APPETITE_CHANGE, maker-checker); WEZA never changes appetite autonomously."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.appetite.mandate import dimensions, validate_mandate
from weza.domains.appetite.models import Appetite, AppetiteVersion
from weza.domains.institution.models import Institution
from weza.domains.matching import engine
from weza.domains.matching.rules import OPS, ruleset_hash
from weza.domains.product.models import Product, ProductVersion
from weza.domains.product.service import RULE_FIELDS
from weza.domains.trust import policy
from weza.domains.trust.service import audit
from weza.platform.context import SYSTEM, Actor
from weza.platform.db import utcnow
from weza.platform.errors import NotFound, ValidationFailed
from weza.platform.events import emit


def _validate(db: Session, actor: Actor, p: dict) -> dict:
    pids = [uuid.UUID(x) for x in p.get("product_ids") or []]
    if not pids:
        raise ValidationFailed("Select at least one product for this appetite.", details=[{"field": "product_ids"}])
    owned = db.execute(select(func.count()).select_from(Product).where(Product.id.in_(pids),
                                                                       Product.institution_id == actor.institution_id)).scalar_one()
    if owned != len(pids):
        raise ValidationFailed("Unknown product.")
    crit = []
    for c in p.get("criteria") or []:
        if c.get("field") not in RULE_FIELDS or c.get("op") not in OPS:
            raise ValidationFailed(f"Unsupported criterion: {c.get('field')} {c.get('op')}.")
        crit.append({"field": c["field"], "op": c["op"], "value": c.get("value"), "label": c.get("label"),
                     "weight": float(c.get("weight") or 1), "must": bool(c.get("must"))})
    mm = int(p.get("min_match_score") or 60)
    if not 0 <= mm <= 100:
        raise ValidationFailed("Minimum match must be between 0 and 100.")
    limits = {k: int(v) for k, v in (p.get("capacity_limits") or {}).items()
              if k in ("daily_count", "weekly_count", "monthly_count", "monthly_value") and v not in (None, "", 0)}

    def d(x):
        return date.fromisoformat(x) if x else None
    mandate = validate_mandate(db, p)
    return {"name": p["name"].strip()[:160], "product_ids": pids, "criteria": crit, "min_match_score": mm,
            "target_count": int(p["target_count"]) if p.get("target_count") else None,
            "target_value": Decimal(str(p["target_value"])) if p.get("target_value") else None,
            "capacity_limits": limits, "campaign_from": d(p.get("campaign_from")), "campaign_to": d(p.get("campaign_to")),
            **mandate}


def _ruleset(av) -> str:
    """The ruleset hash covers the criteria *and* the mandate: changing either changes the rules the
    demand was matched against, so a stored hash can always be compared with the live rules."""
    return ruleset_hash(av.criteria, av.min_match_score, av.customer_types, av.sectors, av.regions,
                        av.min_amount, av.max_amount, av.min_business_age_months)


def create(db: Session, actor: Actor, payload: dict) -> AppetiteVersion:
    policy.require(actor, "appetite.edit")
    v = _validate(db, actor, payload)
    ap = Appetite(institution_id=actor.institution_id, name=v["name"], lifecycle_status="DRAFT")
    db.add(ap)
    db.flush()
    av = AppetiteVersion(appetite_id=ap.id, institution_id=ap.institution_id, version=1, status="DRAFT",
                         author_id=actor.id, **v)
    av.ruleset_hash = _ruleset(av)
    db.add(av)
    db.flush()
    audit(db, actor, "appetite.created", "appetite", ap.id, after={"version": 1})
    return av


def new_version(db: Session, actor: Actor, ap: Appetite, payload: dict) -> AppetiteVersion:
    policy.require(actor, "appetite.edit")
    policy.require_tenant(actor, ap.institution_id)
    v = _validate(db, actor, payload)
    draft = db.execute(select(AppetiteVersion).where(AppetiteVersion.appetite_id == ap.id,
                                                     AppetiteVersion.status.in_(["DRAFT", "SIMULATED"]))).scalar_one_or_none()
    if draft is not None:
        for k, val in v.items():
            setattr(draft, k, val)
        draft.status, draft.simulation_run_id, draft.author_id = "DRAFT", None, actor.id  # edits require re-simulation
        draft.ruleset_hash = _ruleset(draft)
        return draft
    n = db.execute(select(func.max(AppetiteVersion.version)).where(AppetiteVersion.appetite_id == ap.id)).scalar_one() or 0
    av = AppetiteVersion(appetite_id=ap.id, institution_id=ap.institution_id, version=n + 1, status="DRAFT",
                         author_id=actor.id, **v)
    av.ruleset_hash = _ruleset(av)
    db.add(av)
    db.flush()
    audit(db, actor, "appetite.version_drafted", "appetite", ap.id, after={"version": av.version})
    return av


def _product_versions(db: Session, product_ids) -> list[ProductVersion]:
    out = []
    for p in db.execute(select(Product).where(Product.id.in_(product_ids))).scalars():
        vid = p.active_version_id or db.execute(select(ProductVersion.id).where(ProductVersion.product_id == p.id)
                                                .order_by(ProductVersion.version.desc()).limit(1)).scalar_one_or_none()
        if vid:
            out.append(db.get(ProductVersion, vid))
    return out


def simulate_version(db: Session, actor: Actor, av: AppetiteVersion) -> dict:
    policy.require(actor, "appetite.simulate")
    policy.require_tenant(actor, av.institution_id)
    result = engine.simulate(db, av.institution_id, product_versions=_product_versions(db, av.product_ids),
                             criteria=av.criteria, min_match_score=av.min_match_score,
                             mandate=dimensions(av))
    run = engine.record_simulation(db, av.institution_id, "APPETITE", {"appetite_version_id": str(av.id),
                                   "criteria": av.criteria, "min_match_score": av.min_match_score,
                                   "mandate": dimensions(av)}, result,
                                   actor.id, av.id)
    if av.status == "DRAFT":
        av.status = "SIMULATED"
        ap = db.get(Appetite, av.appetite_id)
        if ap.lifecycle_status == "DRAFT":
            ap.lifecycle_status = "SIMULATED"
    av.simulation_run_id = run.id
    audit(db, actor, "appetite.simulated", "appetite", av.appetite_id,
          after={"version": av.version, "inside": result["inside"]})
    emit(db, "AppetiteSimulated", topic="institution", aggregate_type="appetite", aggregate_id=av.appetite_id,
         institution_id=av.institution_id, data={"version": av.version})
    return {"simulation_id": str(run.id), **result}


def simulate_adhoc(db: Session, actor: Actor, payload: dict) -> dict:
    """What-if simulation (no persistence of the appetite) — used by Radius 'simulate a change' and the assistant."""
    policy.require(actor, "appetite.simulate")
    v = _validate(db, actor, {**payload, "name": payload.get("name") or "what-if"})
    result = engine.simulate(db, actor.institution_id, product_versions=_product_versions(db, v["product_ids"]),
                             criteria=v["criteria"], min_match_score=v["min_match_score"],
                             mandate={k: v[k] for k in ("customer_types", "sectors", "regions", "min_amount",
                                                       "max_amount", "min_business_age_months")})
    engine.record_simulation(db, actor.institution_id, "WHAT_IF",
                             {"criteria": v["criteria"], "mandate": {k: v[k] for k in ("customer_types", "sectors",
                                                                                       "regions", "min_amount",
                                                                                       "max_amount",
                                                                                       "min_business_age_months")}},
                             result, actor.id)
    return result


def approve(db: Session, actor: Actor, av: AppetiteVersion, approve_: bool, note: str | None) -> None:
    policy.require(actor, "appetite.activate")
    policy.require_tenant(actor, av.institution_id)
    if av.status != "SIMULATED" or av.simulation_run_id is None:
        raise ValidationFailed("Run a simulation before approving this appetite.", code="SIMULATION_REQUIRED")
    if av.author_id == actor.id:
        raise ValidationFailed("Maker-checker: someone other than the author must approve.", code="MAKER_CHECKER")
    ap = db.get(Appetite, av.appetite_id)
    av.review_note = note
    if not approve_:
        av.status = "REJECTED"
        audit(db, actor, "appetite.rejected", "appetite", ap.id, after={"version": av.version}, reason=note)
        return
    av.status, av.approver_id, av.approved_at = "APPROVED", actor.id, utcnow()
    before = {"status": ap.lifecycle_status, "active_version_id": ap.active_version_id}
    inst = db.get(Institution, ap.institution_id)
    if ap.lifecycle_status in ("ACTIVE", "PAUSED") or inst.status == "ACTIVE":
        _make_current(db, actor, ap, av)
    else:
        ap.lifecycle_status = "APPROVED"
        ap.active_version_id = av.id
    audit(db, actor, "appetite.approved", "appetite", ap.id, before=before,
          after={"version": av.version, "status": ap.lifecycle_status, "active_version_id": ap.active_version_id},
          reason=note)


def _make_current(db: Session, actor: Actor, ap: Appetite, av: AppetiteVersion) -> None:
    now = utcnow()
    if ap.active_version_id and ap.active_version_id != av.id:
        old = db.get(AppetiteVersion, ap.active_version_id)
        if old and old.status == "APPROVED":
            old.status, old.effective_to = "SUPERSEDED", now
    av.effective_from = now
    was_active = ap.lifecycle_status == "ACTIVE"
    ap.active_version_id, ap.name = av.id, av.name
    if ap.lifecycle_status != "PAUSED":
        ap.lifecycle_status = "ACTIVE"
    engine.refresh_capacity(db, ap)
    emit(db, "AppetiteChanged" if was_active else "AppetiteActivated", topic="institution", aggregate_type="appetite",
         aggregate_id=ap.id, institution_id=ap.institution_id, data={"version": av.version})


def activate_appetite(db: Session, actor: Actor, ap: Appetite, from_institution_activation: bool = False) -> None:
    if not from_institution_activation:
        policy.require(actor, "appetite.activate")
        policy.require_tenant(actor, ap.institution_id)
    inst = db.get(Institution, ap.institution_id)
    if inst.status != "ACTIVE":
        raise ValidationFailed("Activate your institution on WEZA first.", code="INSTITUTION_NOT_ACTIVE")
    av = db.get(AppetiteVersion, ap.active_version_id) if ap.active_version_id else None
    if av is None or av.status != "APPROVED":
        raise ValidationFailed("Approve a version of this appetite first.")
    before = ap.lifecycle_status
    _make_current(db, actor, ap, av)
    audit(db, actor, "appetite.activated", "appetite", ap.id, before={"status": before},
          after={"status": ap.lifecycle_status, "version": av.version})


def set_lifecycle(db: Session, actor: Actor, ap: Appetite, to: str, reason: str) -> None:
    if not actor.is_weza:
        policy.require(actor, "appetite.activate")
        policy.require_tenant(actor, ap.institution_id)
    allowed = {"ACTIVE": {"PAUSED", "EXPIRED", "ARCHIVED"}, "PAUSED": {"ACTIVE", "ARCHIVED"},
               "APPROVED": {"ARCHIVED"}, "DRAFT": {"ARCHIVED"}, "SIMULATED": {"ARCHIVED"}}
    if to not in allowed.get(ap.lifecycle_status, set()):
        raise ValidationFailed(f"Appetite cannot move from {ap.lifecycle_status} to {to}.", code="INVALID_TRANSITION")
    # Institution users only (the WEZA admin portal's behaviour is unchanged)
    if to == "ACTIVE" and not actor.is_weza and db.get(Institution, ap.institution_id).status != "ACTIVE":
        raise ValidationFailed("Your institution isn't active on WEZA, so this appetite can't be resumed.",
                               code="INSTITUTION_NOT_ACTIVE")
    before, ap.lifecycle_status = ap.lifecycle_status, to
    audit(db, actor, f"appetite.{to.lower()}", "appetite", ap.id, before={"status": before}, after={"status": to},
          reason=reason)
    emit(db, "AppetiteActivated" if to == "ACTIVE" else "AppetitePaused", topic="institution",
         aggregate_type="appetite", aggregate_id=ap.id, institution_id=ap.institution_id, data={"status": to})


def expiry_sweep(db: Session) -> int:
    """ACTIVE/PAUSED mandates whose campaign has ended move to EXPIRED (terminal). Matching already ignores them
    (engine.active_supply); this makes the lifecycle say so and withdraws them from customers' open options."""
    n = 0
    for ap, av in db.execute(select(Appetite, AppetiteVersion).join(
            AppetiteVersion, AppetiteVersion.id == Appetite.active_version_id).where(
            Appetite.lifecycle_status.in_(["ACTIVE", "PAUSED"]), AppetiteVersion.campaign_to < date.today())).all():
        before, ap.lifecycle_status = ap.lifecycle_status, "EXPIRED"
        audit(db, SYSTEM, "appetite.expired", "appetite", ap.id, before={"status": before}, after={"status": "EXPIRED"},
              reason=f"Campaign ended {av.campaign_to.isoformat()}")
        emit(db, "AppetitePaused", topic="institution", aggregate_type="appetite", aggregate_id=ap.id,
             institution_id=ap.institution_id, data={"status": "EXPIRED"})
        n += 1
    return n


def set_capacity_override(db: Session, actor: Actor, ap: Appetite, override: str | None, reason: str) -> None:
    policy.require(actor, "appetite.edit")
    policy.require_tenant(actor, ap.institution_id)
    if override not in (None, "PAUSED", "LIMITED"):
        raise ValidationFailed("Override must be PAUSED, LIMITED or cleared.")
    before = {"override": ap.capacity_override, "capacity_state": ap.capacity_state}
    ap.capacity_override = override
    ap.capacity_state = override or "ACTIVE"
    engine.refresh_capacity(db, ap)
    audit(db, actor, "appetite.capacity_override", "appetite", ap.id, before=before,
          after={"override": override, "capacity_state": ap.capacity_state}, reason=reason)
    emit(db, "CapacityChanged", topic="institution", aggregate_type="appetite", aggregate_id=ap.id,
         institution_id=ap.institution_id, data={"to": ap.capacity_state, "manual": True})


def get_owned(db: Session, actor: Actor, appetite_id: uuid.UUID) -> Appetite:
    query = select(Appetite).where(Appetite.id == appetite_id)
    if not actor.is_weza:
        query = query.where(Appetite.institution_id == actor.institution_id)
    ap = db.execute(query).scalar_one_or_none()
    if ap is None:
        raise NotFound("Not found.")
    policy.require_tenant(actor, ap.institution_id)
    return ap
