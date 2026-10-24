"""WEZA Administration & Network Control Centre (FSD §41; Skill §59): verification, network controls,
Human Control Centre, integrity, disputes, commercial, Graph Inspector, audit and configuration."""

import uuid
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from weza.api.deps import DB, require_step_up, weza_actor
from weza.domains.admin_config import get_config, publish_config
from weza.domains.appetite import service as appetite_svc
from weza.domains.appetite.models import Appetite
from weza.domains.commercial import referral as referrals
from weza.domains.commercial import service as commercial
from weza.domains.commercial.models import CommercialEvent, Contract, Dispute
from weza.domains.consent.models import Consent
from weza.domains.customer.models import Customer
from weza.domains.identity.models import Membership, User
from weza.domains.identity.service import mask_phone, vault_find_by_phone, vault_read
from weza.domains.institution import service as inst_svc
from weza.domains.institution.models import Contact, Institution
from weza.domains.intelligence import insights
from weza.domains.intelligence.parsing import parse_phone
from weza.domains.matching.models import ClearingRun, Match, ShadowMatch
from weza.domains.misc_models import AgentStep, AiCallLog, IntegrityCase, LoopMetric, Notification, ReviewItem
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import Assignment, Opportunity, Outcome
from weza.domains.product import service as product_svc
from weza.domains.product.models import Product
from weza.domains.trust import policy, retention
from weza.domains.trust.models import AuditEvent, Decision
from weza.domains.trust.service import audit
from weza.platform.context import Actor
from weza.platform.controls import rate_limit
from weza.platform.db import session_scope, utcnow
from weza.platform.errors import Forbidden, InvalidTransition, NotFound, ValidationFailed
from weza.platform.events import emit, replay_delivery
from weza.platform.models import (
    EventDelivery,
    FeatureFlag,
    GraphInstance,
    GraphTransition,
    KillSwitch,
    OutboxEvent,
)

router = APIRouter(prefix="/admin", tags=["admin"])
W = Depends(weza_actor)
KILL_SWITCHES = {"pause_all_routing": "Pause all routing", "pause_billing_events": "Pause billing-event creation",
                 "disabled_channels": "Disabled channels", "ai_mode": "AI mode"}
FLAGS = {"marketplace.preview": "Opportunity Preview & Institution Interest",
         "channel.whatsapp_simulator": "WhatsApp simulator (test)", "matching.shadow": "Shadow algorithm comparison"}


@router.get("/overview")
def overview(actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    ms = insights.market_state(db)
    queues = dict(db.execute(select(ReviewItem.kind, func.count()).where(ReviewItem.status == "OPEN")
                             .group_by(ReviewItem.kind)).all())
    insts = Counter(s for (s,) in db.execute(select(Institution.status)).all())
    resp = []
    for inst in db.execute(select(Institution).where(Institution.status.in_(["ACTIVE", "PAUSED"]))).scalars():
        rows = db.execute(select(Opportunity, Assignment).outerjoin(Assignment, Assignment.opportunity_id == Opportunity.id)
                          .where(Opportunity.institution_id == inst.id)).all()
        contacted = [(a.first_contact_at - o.routed_at).total_seconds() / 3600 for o, a in rows
                     if a and a.first_contact_at and o.routed_at]
        resp.append({"institution": inst.display_name, "id": str(inst.id), "status": inst.status,
                     "opportunities": len(rows), "breaches": sum(1 for _, a in rows if a and a.breach_count),
                     "avg_first_contact_h": round(sum(contacted) / len(contacted), 1) if contacted else None,
                     "unassigned": sum(1 for o, a in rows if (a is None or a.user_id is None)
                                       and o.state in opp_svc.OPEN_STATES)})
    paused = {"products": db.execute(select(func.count()).select_from(Product).where(Product.status == "PAUSED")).scalar_one(),
              "mandates": db.execute(select(func.count()).select_from(Appetite)
                                     .where(Appetite.lifecycle_status == "PAUSED")).scalar_one()}
    return {"market": ms, "queues": queues, "institutions_by_status": dict(insts), "responsiveness": resp,
            "paused_supply": paused,
            "kill_switches": {k: (db.get(KillSwitch, k).value if db.get(KillSwitch, k) else {}) for k in KILL_SWITCHES}}


# ------------------------------------------------------------------ institutions


@router.get("/institutions")
def institutions(actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    rows = db.execute(select(Institution).order_by(Institution.created_at.desc())).scalars()
    return {"institutions": [{**inst_svc.summary(i), "created_at": i.created_at.isoformat()} for i in rows]}


@router.get("/institutions/{inst_id}")
def institution(inst_id: uuid.UUID, actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    i = db.get(Institution, inst_id)
    if i is None:
        raise NotFound("Not found.")
    return {**inst_svc.summary(i), "status_reason": i.status_reason, "profile": i.profile,
            "primary_contact": inst_svc.primary_contact(db, i),
            "contacts": [inst_svc.contact_summary(c)
                         for c in db.execute(select(Contact).where(Contact.institution_id == i.id)).scalars()],
            "checklist": inst_svc.checklist(db, i),
            "users": db.execute(select(func.count()).select_from(Membership).where(
                Membership.institution_id == i.id)).scalar_one(),
            "products": [{"id": str(p.id), "name": p.name, "status": p.status} for p in db.execute(
                select(Product).where(Product.institution_id == i.id)).scalars()],
            "appetites": [{"id": str(a.id), "name": a.name, "status": a.lifecycle_status, "capacity": a.capacity_state}
                          for a in db.execute(select(Appetite).where(Appetite.institution_id == i.id)).scalars()],
            "allowed_transitions": sorted(inst_svc.INSTITUTION_SM.transitions.get(i.status, set()))}


class VerifyIn(BaseModel):
    approve: bool
    reason: str = Field(..., min_length=3, max_length=1000)


@router.post("/institutions/{inst_id}/verify")
def verify(inst_id: uuid.UUID, body: VerifyIn, actor: Actor = W, db: Session = DB):
    i = db.get(Institution, inst_id)
    if i is None:
        raise NotFound("Not found.")
    inst_svc.verify(db, actor, i, body.approve, body.reason)
    return institution(inst_id, actor, db)


class StatusIn(BaseModel):
    status: str
    reason: str = Field(..., min_length=3, max_length=1000)


@router.post("/institutions/{inst_id}/status")
def institution_status(inst_id: uuid.UUID, body: StatusIn, actor: Actor = W, db: Session = DB):
    """Network health control (FSD FR-040, TSD §75): pause/suspend without affecting other participants."""
    policy.require(actor, "admin.network_control")
    require_step_up(actor)
    i = db.get(Institution, inst_id)
    if i is None:
        raise NotFound("Not found.")
    inst_svc.set_status(db, actor, i, body.status, body.reason)
    return institution(inst_id, actor, db)


def _pause_or_resume(status: str) -> None:
    """WEZA may pause or resume supply (09-api; TSD §75) but never edits eligibility or archives it (BR-004)."""
    if status not in ("PAUSED", "ACTIVE"):
        raise ValidationFailed("WEZA can only pause or resume products and mandates.")


@router.post("/products/{product_id}/status")
def product_status(product_id: uuid.UUID, body: StatusIn, actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.network_control")
    require_step_up(actor)
    _pause_or_resume(body.status)
    p = db.get(Product, product_id)
    if p is None:
        raise NotFound("Not found.")
    product_svc.set_status(db, actor, p, body.status, body.reason)
    return {"ok": True, "status": p.status}


@router.post("/appetites/{appetite_id}/status")
def appetite_status(appetite_id: uuid.UUID, body: StatusIn, actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.network_control")
    require_step_up(actor)
    _pause_or_resume(body.status)
    a = db.get(Appetite, appetite_id)
    if a is None:
        raise NotFound("Not found.")
    appetite_svc.set_lifecycle(db, actor, a, body.status, body.reason)
    return {"ok": True, "status": a.lifecycle_status}


# ------------------------------------------------------------------ market, opportunities, customers


@router.get("/market")
def market(actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    runs = db.execute(select(ClearingRun).order_by(ClearingRun.started_at.desc()).limit(20)).scalars().all()
    shadow = None
    if runs:
        last = runs[0]
        prod = db.execute(select(func.count(), func.avg(Match.score)).where(Match.clearing_run_id == last.id,
                                                                             Match.state.in_(["RANKED", "PRESENTED",
                                                                                              "SELECTED"]))).one()
        sh = db.execute(select(func.count(), func.avg(ShadowMatch.score)).where(ShadowMatch.clearing_run_id == last.id,
                                                                                ShadowMatch.eligible.is_(True))).one()
        shadow = {"run_id": str(last.id), "production": {"eligible_matches": prod[0], "avg_score": round(prod[1] or 0, 1)},
                  "shadow": {"algorithm": last.shadow_algorithm_version, "eligible_matches": sh[0],
                             "avg_score": round(sh[1] or 0, 1)},
                  "note": "Shadow results never affect customers (Skill §56)."}
    return {"state": insights.market_state(db), "demand": insights.demand_intelligence(db),
            "clearing_runs": [{"id": str(r.id), "trigger": r.trigger_event, "started_at": r.started_at.isoformat(),
                               "needs": r.needs_evaluated, "matches": r.matches_created,
                               "newly_matched": r.newly_matched_needs, "ms": r.duration_ms} for r in runs],
            "shadow": shadow}


@router.get("/opportunities")
def opportunities(state: str | None = None, freshness: str | None = None, q: str | None = None,
                  actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    query = select(Opportunity)
    if state:
        query = query.where(Opportunity.state == state)
    if freshness:
        query = query.where(Opportunity.freshness == freshness)
    if q:
        query = query.where(Opportunity.reference.ilike(f"%{q[:20]}%"))
    rows = db.execute(query.order_by(Opportunity.qualified_at.desc()).limit(200)).scalars().all()
    names = {i.id: i.display_name for i in db.execute(select(Institution)).scalars()}
    return {"items": [{**opp_svc.summary(db, o), "institution": names.get(o.institution_id)} for o in rows]}


class LookupIn(BaseModel):
    phone: str = Field(..., max_length=40)
    reason: str = Field(..., max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5:
            raise ValueError("Give a reason of at least 5 characters.")
        return v


@router.post("/customers/lookup")
def customer_lookup(body: LookupIn, actor: Actor = W, db: Session = DB):
    """Support lookup via the Identity Vault — requires a reason, is audited, masks identifiers (blueprint A-05)."""
    rate_limit(db, f"admin:customer_lookup:{actor.id}", 30, 600)
    try:
        policy.require(actor, "admin.vault_lookup")
        require_step_up(actor)
    except Forbidden as exc:
        # The request transaction rolls back on error, so the denied attempt is recorded in its own session.
        with session_scope() as own:
            audit(own, actor, "vault.lookup_denied", "vault", "none", reason=body.reason, after={"code": exc.code})
            emit(own, "PrivilegedAccess", topic="audit", aggregate_type="vault", aggregate_id="none",
                 data={"action": "vault.lookup", "outcome": "DENIED"})
        raise
    phone = parse_phone(body.phone)
    rec = vault_find_by_phone(db, phone) if phone else None
    audit(db, actor, "vault.lookup", "vault", rec.id if rec else "none", reason=body.reason)
    emit(db, "PrivilegedAccess", topic="audit", aggregate_type="vault", aggregate_id=rec.id if rec else "none",
         data={"action": "vault.lookup", "outcome": "FOUND" if rec else "NOT_FOUND"})
    if rec is None:
        return {"found": False}
    cust = db.execute(select(Customer).where(Customer.vault_token == rec.id)).scalar_one()
    v = vault_read(db, rec.id)
    needs = db.execute(select(FinancialNeed).where(FinancialNeed.customer_id == cust.id)
                       .order_by(FinancialNeed.created_at.desc())).scalars().all()
    from weza.domains.need.service import need_summary
    name = v.get("full_name") or ""
    return {"found": True, "customer": {"id": str(cust.id), "phone": mask_phone(v.get("phone")),
                                        "name": (name.split()[0] + " " + name.split()[-1][:1] + ".") if name else None,
                                        "type": cust.customer_type, "integrity_state": cust.integrity_state,
                                        "verification": cust.verification_level, "status": cust.status},
            "needs": [need_summary(n) for n in needs],
            "opportunities": [opp_svc.summary(db, o) for o in db.execute(select(Opportunity).where(
                Opportunity.customer_id == cust.id)).scalars()]}


# ------------------------------------------------------------------ Human Control Centre


@router.get("/review")
def review(status: str = "OPEN", actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    rows = db.execute(select(ReviewItem).where(ReviewItem.status == status).order_by(ReviewItem.created_at.desc())
                      .limit(200)).scalars()
    return {"items": [{"id": str(r.id), "kind": r.kind, "title": r.title, "object_type": r.object_type,
                       "object_id": r.object_id, "severity": r.severity, "detail": r.detail, "status": r.status,
                       "created_at": r.created_at.isoformat(), "due_at": r.due_at.isoformat() if r.due_at else None,
                       "resolution": r.resolution} for r in rows]}


class ResolveIn(BaseModel):
    action: str = Field(..., pattern="^(release|close|replay|dismiss|resolve)$")
    note: str = Field(..., min_length=3, max_length=1000)


@router.post("/review/{item_id}/resolve")
def resolve(item_id: uuid.UUID, body: ResolveIn, actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.review")
    item = db.get(ReviewItem, item_id)
    if item is None:
        raise NotFound("Not found.")
    if item.status != "OPEN":
        raise InvalidTransition("This item has already been resolved.", details=[{"from": item.status}])
    if item.kind == "DUPLICATE_HOLD" and body.action in ("release", "close"):
        opp = db.get(Opportunity, uuid.UUID(item.object_id))
        if body.action == "release":
            opp_svc.route(db, opp, actor)
        else:
            opp.state, opp.closed_at, opp.integrity_hold = "CLOSED", utcnow(), False
            emit(db, "OpportunityClosed", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
                 institution_id=opp.institution_id, data={"reason": "duplicate"})
    elif item.kind == "DEAD_LETTER" and body.action == "replay":
        replay_delivery(db, uuid.UUID(item.object_id))
    item.status, item.resolved_by, item.resolution = "RESOLVED", actor.display, f"{body.action}: {body.note}"
    audit(db, actor, f"review.{body.action}", item.object_type, item.object_id, reason=body.note,
          before={"kind": item.kind, "status": "OPEN"}, after={"kind": item.kind, "status": item.status})
    return review("OPEN", actor, db)


@router.get("/integrity")
def integrity_cases(actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    rows = db.execute(select(IntegrityCase).order_by(IntegrityCase.created_at.desc()).limit(200)).scalars()
    return {"cases": [{"id": str(c.id), "subject_type": c.subject_type, "subject_id": c.subject_id, "score": c.score,
                       "risk_state": c.risk_state, "state": c.state, "result": c.result, "signals": c.signals,
                       "context": c.context, "created_at": c.created_at.isoformat(), "note": c.decision_note}
                      for c in rows],
            "note": "Integrity protects the marketplace. It is never a creditworthiness decision."}


class CaseDecision(BaseModel):
    result: str = Field(..., pattern="^(ALLOW|BLOCK)$")
    note: str = Field(..., min_length=3, max_length=1000)


@router.post("/integrity/{case_id}/decide")
def decide_case(case_id: uuid.UUID, body: CaseDecision, actor: Actor = W, db: Session = DB):
    """HUMAN_REVIEW_INTEGRITY_CASE (AL0)."""
    policy.require(actor, "admin.review")
    c = db.get(IntegrityCase, case_id)
    if c is None:
        raise NotFound("Not found.")
    if c.state != "OPEN":
        raise InvalidTransition("This case has already been decided.", details=[{"from": c.state}])
    c.state, c.result, c.decided_by, c.decision_note = "DECIDED", body.result, actor.id, body.note
    if c.subject_type == "opportunity":
        opp = db.get(Opportunity, uuid.UUID(c.subject_id))
        cust = db.get(Customer, opp.customer_id)
        if body.result == "ALLOW":
            cust.integrity_state = "NORMAL"
            opp_svc.route(db, opp, actor)
        else:
            cust.integrity_state = "BLOCKED"
            opp.state, opp.closed_at = "CLOSED", utcnow()
    for item in db.execute(select(ReviewItem).where(ReviewItem.object_id == str(c.id))).scalars():
        item.status, item.resolved_by, item.resolution = "RESOLVED", actor.display, body.result
    audit(db, actor, "integrity.decided", "integrity_case", c.id, before={"state": "OPEN"},
          after={"state": "DECIDED", "result": body.result}, reason=body.note)
    emit(db, "IntegrityCaseDecided", topic="integrity", aggregate_type="integrity_case", aggregate_id=c.id,
         data={"result": body.result})
    return integrity_cases(actor, db)


# ------------------------------------------------------------------ commercial & disputes


@router.get("/disputes")
def disputes(actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    names = {i.id: i.display_name for i in db.execute(select(Institution)).scalars()}
    rows = db.execute(select(Dispute).order_by(Dispute.created_at.desc()).limit(200)).scalars()
    out = []
    for d in rows:
        ev = db.get(CommercialEvent, d.commercial_event_id)
        opp = db.get(Opportunity, d.opportunity_id) if d.opportunity_id else None
        out.append({"id": str(d.id), "institution": names.get(d.institution_id), "reason": d.reason,
                    "reason_label": commercial.DISPUTE_REASONS.get(d.reason), "description": d.description,
                    "state": d.state, "decision": d.decision, "amount": float(ev.amount) if ev else 0,
                    "reference": opp.reference if opp else None, "history": d.history,
                    "opportunity_state": opp.state if opp else None, "created_at": d.created_at.isoformat(),
                    "allowed": sorted(commercial.DISPUTE_SM.transitions.get(d.state, set()))})
    return {"disputes": out}


class DisputeMove(BaseModel):
    state: str
    decision: str | None = None
    note: str = Field("", max_length=2000)


@router.post("/disputes/{dispute_id}/move")
def move_dispute(dispute_id: uuid.UUID, body: DisputeMove, actor: Actor = W, db: Session = DB):
    """AUTHORISED_COMMERCIAL_REVIEW (AL0). Reversals/credits are new events, never edits (Skill §49)."""
    policy.require(actor, "admin.dispute_decide")
    if body.state == "DECIDED" and len(body.note.strip()) < 3:
        raise ValidationFailed("Record the reason and evidence for this decision.")  # FSD §42; admin journey
    commercial.move_dispute(db, actor, dispute_id, body.state, body.note.strip(), body.decision)
    return disputes(actor, db)


@router.get("/commercial")
def commercial_overview(actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    period = utcnow().strftime("%Y-%m")
    out = []
    ai_cost = db.execute(select(func.coalesce(func.sum(AiCallLog.cost_usd), 0))).scalar_one()
    total_opps = db.execute(select(func.count()).select_from(Opportunity)).scalar_one()
    for inst in db.execute(select(Institution).where(Institution.status.in_(["ACTIVE", "PAUSED"]))).scalars():
        st = commercial.statement(db, inst.id, period)
        c = commercial.active_contract(db, inst.id)
        n = db.execute(select(func.count()).select_from(Opportunity).where(Opportunity.institution_id == inst.id)).scalar_one()
        out.append({"institution": inst.display_name, "institution_id": str(inst.id), "statement": st,
                    "opportunities_total": n,
                    "contract": {"plan": c.plan, "subscription_fee": float(c.subscription_fee),
                                 "included_opportunities": c.included_opportunities,
                                 "opportunity_price": float(c.opportunity_price),
                                 "duplicate_window_days": c.duplicate_window_days,
                                 "dispute_window_days": c.dispute_window_days,
                                 "min_match_score": commercial.qualified_definition(c)["min_match_score"]}
                    if c else None})
    revenue = sum(x["statement"]["total_due"] for x in out)
    return {"period": period, "institutions": out, "unit_economics": {
        "revenue_month": revenue, "qualified_opportunities_total": total_opps,
        "revenue_per_opportunity": round(revenue / total_opps) if total_opps else None,
        "ai_cost_usd_total": round(float(ai_cost), 4),
        "ai_cost_usd_per_opportunity": round(float(ai_cost) / total_opps, 4) if total_opps else None}}


class ContractIn(BaseModel):
    plan: str = Field(..., max_length=30)
    subscription_fee: float = Field(..., ge=0)
    included_opportunities: int = Field(..., ge=0)
    opportunity_price: float = Field(..., ge=0)
    duplicate_window_days: int = Field(30, ge=1, le=365)
    dispute_window_days: int = Field(14, ge=1, le=90)
    min_match_score: int = Field(60, ge=0, le=100)


@router.put("/contracts/{inst_id}")
def set_contract(inst_id: uuid.UUID, body: ContractIn, actor: Actor = W, db: Session = DB):
    """Contract-configurable commercial definitions (TSD §44). Old contract is end-dated, never edited."""
    policy.require(actor, "admin.commercial")
    if db.get(Institution, inst_id) is None:
        raise NotFound("Not found.")
    previous = commercial.active_contract(db, inst_id)
    # Carry over every other qualification rule; only the match threshold is edited here.
    definition = {**((previous.qualified_definition if previous else {}) or {}), "min_match_score": body.min_match_score}
    for c in db.execute(select(Contract).where(Contract.institution_id == inst_id, Contract.status == "ACTIVE")).scalars():
        c.status, c.effective_to = "ENDED", date.today()
    db.add(Contract(institution_id=inst_id, plan=body.plan, subscription_fee=Decimal(str(body.subscription_fee)),
                    included_opportunities=body.included_opportunities,
                    opportunity_price=Decimal(str(body.opportunity_price)),
                    duplicate_window_days=body.duplicate_window_days, dispute_window_days=body.dispute_window_days,
                    qualified_definition=definition, effective_from=date.today()))
    audit(db, actor, "contract.updated", "institution", inst_id, after=body.model_dump())
    return commercial_overview(actor, db)


# ------------------------------------------------------------------ partner and campaign links (BRD §5, TSD §73)


@router.get("/referral-links")
def referral_link(source: str | None = Query(None, max_length=40), campaign: str | None = Query(None, max_length=40),
                  partner: str | None = Query(None, max_length=40), referral: str | None = Query(None, max_length=40),
                  text: str = Query("Hi", max_length=200), actor: Actor = W, db: Session = DB):
    """A click-to-WhatsApp link and a printable QR code that tag every customer who arrives through it with its source,
    campaign, partner and referral code. Generating one changes nothing: the lineage is recorded when a customer
    actually arrives."""
    policy.require(actor, "admin.commercial")
    link = referrals.whatsapp_link(source, campaign, partner, referral, text)
    ref = referrals.reference(source, campaign, partner, referral)
    audit(db, actor, "referral_link.created", "referral_link", ref[:64], after={"reference": ref})
    return {"link": link, "reference": ref, "qr_svg": referrals.qr_svg(link)}


# ------------------------------------------------------------------ retention (TSD §70)


@router.get("/retention")
def retention_preview(actor: Actor = W, db: Session = DB):
    """What the retention engine would do right now. Changes nothing."""
    policy.require(actor, "admin.config")
    return retention.run(db, apply=False)


class RetentionRun(BaseModel):
    reason: str = Field(..., min_length=8, max_length=300)


@router.post("/retention/run")
def retention_run(body: RetentionRun, actor: Actor = W, db: Session = DB):
    """Carry out the retention policy now (it also runs daily when RETENTION_ENABLED). Deletes data, so it needs MFA
    step-up and a recorded reason."""
    rate_limit(db, f"admin:retention_run:{actor.id}", 5, 3600)
    policy.require(actor, "admin.config")
    require_step_up(actor)
    report = retention.run(db, apply=True)
    audit(db, actor, "retention.run_manual", "retention", "manual", reason=body.reason,
          after={"customers_anonymised": report["customers"]["anonymise"],
                 "rules": {k: v["done"] for k, v in report["rules"].items()}})
    return report


# ------------------------------------------------------------------ Graph Inspector (Skill §59)


@router.get("/graph")
def graph_inspector(q: str = Query(..., min_length=3, max_length=80), actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.engineering")
    audit(db, actor, "graph.inspected", "graph", q[:64])
    opp = need = None
    if q.upper().startswith("OPP-"):
        opp = db.execute(select(Opportunity).where(Opportunity.reference == q.upper())).scalar_one_or_none()
    else:
        try:
            uid = uuid.UUID(q)
        except ValueError as exc:
            raise ValidationFailed("Search by opportunity reference (OPP-…) or an ID.") from exc
        opp = db.get(Opportunity, uid)
        need = db.get(FinancialNeed, uid)
        if opp is None and need is None:
            gi = db.get(GraphInstance, uid)
            if gi and gi.need_id:
                need = db.get(FinancialNeed, gi.need_id)
            m = db.get(Match, uid)
            if m:
                need = db.get(FinancialNeed, m.need_id)
    if opp is not None:
        need = db.get(FinancialNeed, opp.need_id)
    if need is None:
        raise NotFound("Nothing found for that reference.")
    nodes, edges = [], []

    def node(id_, kind, label, data=None):
        nodes.append({"id": str(id_), "kind": kind, "label": label, "data": data or {}})

    def edge(a, b, rel):
        edges.append({"from": str(a), "to": str(b), "rel": rel})

    cust = db.get(Customer, need.customer_id) if need.customer_id else None
    if cust:
        node(cust.id, "Customer", f"Customer ({cust.customer_type or '—'})",
             {"verification": cust.verification_level, "integrity": cust.integrity_state})
        edge(cust.id, need.id, "HAS_NEED")
    from weza.domains.need.service import need_summary
    node(need.id, "FinancialNeed", f"Need · {need.purpose or need.purpose_category or ''}", need_summary(need))
    matches = db.execute(select(Match).where(Match.need_id == need.id).order_by(Match.created_at.desc()).limit(25)).scalars().all()
    names = {i.id: i.display_name for i in db.execute(select(Institution)).scalars()}
    for m in matches:
        node(m.id, "Match", f"Match {round(m.score)} · {names.get(m.institution_id)}",
             {"state": m.state, "score": m.score, "components": m.components, "readiness": m.readiness,
              "algorithm": m.algorithm_version, "weights": m.weights_version, "ruleset": m.ruleset_hash,
              "explanation": m.explanation, "invalidated_reason": m.invalidated_reason})
        edge(need.id, m.id, "GENERATES")
        edge(m.id, m.institution_id, "CONNECTS")
    for iid in {m.institution_id for m in matches}:
        node(iid, "Institution", names.get(iid, "Institution"))
    opps = db.execute(select(Opportunity).where(Opportunity.need_id == need.id)).scalars().all()
    for o in opps:
        node(o.id, "Opportunity", f"{o.reference} · {o.state}", {"state": o.state, "freshness": o.freshness,
                                                                 "snapshot": o.snapshot, "priority": o.priority})
        c = db.get(Consent, o.consent_id)
        if c:
            node(c.id, "Consent", f"Consent v{c.template_version} · {c.status}",
                 {"categories": c.data_categories, "text_hash": c.text_hash, "granted_at": c.granted_at.isoformat()})
            edge(c.id, o.id, "AUTHORISES")
            if cust:
                edge(cust.id, c.id, "GRANTS")
        edge(o.match_id, o.id, "QUALIFIES_AS")
        edge(o.id, o.institution_id, "ROUTED_TO")
        a = db.get(Assignment, o.id)
        if a and a.user_id:
            u = db.get(User, a.user_id)
            node(f"user:{a.user_id}", "Officer", u.full_name if u else "Officer", {"breach": a.breach_state})
            edge(o.id, f"user:{a.user_id}", "ASSIGNED_TO")
        for out in db.execute(select(Outcome).where(Outcome.opportunity_id == o.id)).scalars():
            node(out.id, "Outcome", f"{out.state} (reported)", {"reason": out.reason_category,
                                                                "disbursed": float(out.disbursed_amount or 0)})
            edge(o.id, out.id, "PRODUCES")
        for ev in db.execute(select(CommercialEvent).where(CommercialEvent.opportunity_id == o.id)).scalars():
            node(ev.id, "CommercialEvent", f"{ev.kind} · {ev.status} · {float(ev.amount):,.0f}", {"evaluation": ev.evaluation})
            edge(o.id, ev.id, "GENERATES")
    agg_ids = [str(need.id)] + [str(o.id) for o in opps] + ([str(cust.id)] if cust else [])
    events = db.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id.in_(agg_ids))
                        .order_by(OutboxEvent.occurred_at).limit(300)).scalars().all()
    deliveries = db.execute(select(EventDelivery).where(EventDelivery.event_id.in_([e.id for e in events]))).scalars().all() \
        if events else []
    dmap: dict = {}
    for d in deliveries:
        dmap.setdefault(d.event_id, []).append({"consumer": d.consumer, "status": d.status, "attempts": d.attempts,
                                                "error": d.last_error})
    decisions = db.execute(select(Decision).where(Decision.subject_id.in_(agg_ids)).order_by(Decision.at)).scalars().all()
    gi = db.get(GraphInstance, need.journey_id) if need.journey_id else None
    transitions = db.execute(select(GraphTransition).where(GraphTransition.instance_id == gi.id)
                             .order_by(GraphTransition.at)).scalars().all() if gi else []
    audits = db.execute(select(AuditEvent).where(AuditEvent.object_id.in_(agg_ids + [str(o.consent_id) for o in opps]))
                        .order_by(AuditEvent.at)).scalars().all()
    ai_calls = db.execute(select(AiCallLog).where(AiCallLog.subject == str(need.id)).order_by(AiCallLog.created_at)).scalars().all()
    agent_steps = db.execute(select(AgentStep).where(AgentStep.subject == str(need.id))
                             .order_by(AgentStep.created_at)).scalars().all()
    return {
        "nodes": nodes, "edges": edges,
        "graph": {"id": str(gi.id), "type": gi.graph_type, "version": gi.graph_version, "current_node": gi.current_node,
                  "status": gi.status, "waiting_for": gi.waiting_for, "attempts": gi.attempt_count,
                  "next_action_at": gi.next_action_at.isoformat() if gi.next_action_at else None,
                  "error": gi.error_state,
                  "state": {k: v for k, v in gi.state.items() if k not in ("phone_enc", "channel_phone_enc", "ip",
                                                                             "device_hash", "wa_index")}} if gi else None,
        "transitions": [{"from": t.from_node, "to": t.to_node, "trigger": t.trigger, "autonomy": t.autonomy_level,
                         "actor": t.actor, "at": t.at.isoformat()} for t in transitions],
        "events": [{"type": e.event_type, "topic": e.topic, "at": e.occurred_at.isoformat(), "data": e.data,
                    "deliveries": dmap.get(e.id, [])} for e in events],
        "decisions": [{"type": d.decision_type, "at": d.at.isoformat(), "ruleset": d.ruleset_version,
                       "algorithm": d.algorithm_version, "output": d.output, "inputs": d.input_snapshot}
                      for d in decisions],
        "audit": [{"at": a.at.isoformat(), "actor": a.actor_display, "action": a.action, "reason": a.reason}
                  for a in audits],
        "ai_calls": [{"capability": c.capability, "mode": c.mode, "model": c.model, "fallback": c.fallback_used,
                      "latency_ms": c.latency_ms, "tokens": c.input_tokens + c.output_tokens, "error": c.error,
                      "at": c.created_at.isoformat()} for c in ai_calls],
        "agent_steps": [{"agent": s.agent, "tool": s.tool, "status": s.result_status,
                         "latency_ms": s.latency_ms, "args_hash": s.args_hash,
                         "at": s.created_at.isoformat()} for s in agent_steps],
    }


# ------------------------------------------------------------------ audit, notifications, deliveries


@router.get("/audit")
def audit_log(action: str | None = None, object_id: str | None = None, limit: int = Query(200, le=1000),
              actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    q = select(AuditEvent)
    if action:
        q = q.where(AuditEvent.action.ilike(f"%{action[:60]}%"))
    if object_id:
        q = q.where(AuditEvent.object_id == object_id[:64])
    rows = db.execute(q.order_by(AuditEvent.at.desc()).limit(limit)).scalars()
    names = {i.id: i.display_name for i in db.execute(select(Institution)).scalars()}
    return {"events": [{"at": a.at.isoformat(), "actor_type": a.actor_type, "actor": a.actor_display,
                        "institution": names.get(a.institution_id), "action": a.action, "object": a.object_type,
                        "object_id": a.object_id, "reason": a.reason, "before": a.before, "after": a.after,
                        "correlation_id": a.correlation_id} for a in rows]}


@router.get("/deliveries")
def deliveries(status: str = "DEAD", actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.engineering")
    rows = db.execute(select(EventDelivery, OutboxEvent).join(OutboxEvent, OutboxEvent.id == EventDelivery.event_id)
                      .where(EventDelivery.status == status).order_by(EventDelivery.next_attempt_at.desc()).limit(200)).all()
    failed_notes = db.execute(select(Notification).where(Notification.status.in_(["FAILED", "DEAD"]))
                              .order_by(Notification.created_at.desc()).limit(100)).scalars()
    return {"deliveries": [{"id": str(d.id), "consumer": d.consumer, "event": e.event_type, "critical": d.critical,
                            "attempts": d.attempts, "error": d.last_error, "status": d.status,
                            "at": e.occurred_at.isoformat()} for d, e in rows],
            "notification_failures": [{"id": str(n.id), "title": n.title, "channel": n.channel, "status": n.status,
                                       "error": n.last_error, "attempts": n.attempts} for n in failed_notes]}


@router.post("/deliveries/{delivery_id}/replay")
def replay(delivery_id: uuid.UUID, actor: Actor = W, db: Session = DB):
    """Controlled replay — idempotent consumers guarantee no duplicate opportunities, charges or messages."""
    policy.require(actor, "admin.review")
    replay_delivery(db, delivery_id)
    audit(db, actor, "event.replayed", "event_delivery", delivery_id)
    return {"ok": True}


@router.get("/notifications")
def my_notifications(actor: Actor = W, db: Session = DB):
    rows = db.execute(select(Notification).where(Notification.recipient_id == actor.id)
                      .order_by(Notification.created_at.desc()).limit(50)).scalars()
    return {"notifications": [{"id": str(n.id), "title": n.title, "body": n.body, "link": n.link, "priority": n.priority,
                               "at": n.created_at.isoformat(), "read": n.read_at is not None} for n in rows]}


@router.get("/loops")
def loops(actor: Actor = W, db: Session = DB):
    """Loop & graph observability (Skill §61; blueprint 08 §6)."""
    policy.require(actor, "admin.engineering")
    since = utcnow() - timedelta(days=30)
    node_entries = db.execute(select(GraphTransition.to_node, func.count()).where(GraphTransition.at >= since)
                              .group_by(GraphTransition.to_node)).all()
    statuses = db.execute(select(GraphInstance.graph_type, GraphInstance.status, func.count())
                          .group_by(GraphInstance.graph_type, GraphInstance.status)).all()
    waiting_at = db.execute(select(GraphInstance.current_node, func.count()).where(
        GraphInstance.status == "WAITING").group_by(GraphInstance.current_node)).all()
    loop_metrics = db.execute(select(LoopMetric.loop, LoopMetric.event, func.count()).where(LoopMetric.created_at >= since)
                              .group_by(LoopMetric.loop, LoopMetric.event)).all()
    ai = db.execute(select(AiCallLog.capability, func.count(), func.avg(AiCallLog.latency_ms),
                           func.sum(AiCallLog.input_tokens + AiCallLog.output_tokens),
                           func.count().filter(AiCallLog.fallback_used.is_(True)),
                           func.count().filter(AiCallLog.validation_ok.is_(False)))
                    .where(AiCallLog.created_at >= since).group_by(AiCallLog.capability)).all()
    agent_steps = db.execute(select(AgentStep.agent, AgentStep.tool, AgentStep.result_status, func.count())
                             .where(AgentStep.created_at >= since)
                             .group_by(AgentStep.agent, AgentStep.tool, AgentStep.result_status)).all()
    return {"node_entries": dict(node_entries),
            "instances": [{"graph": g, "status": s, "count": c} for g, s, c in statuses],
            "waiting_at": dict(waiting_at),
            "loops": [{"loop": loop, "event": e, "count": c} for loop, e, c in loop_metrics],
            "agent_steps": [{"agent": a, "tool": t, "status": s, "count": n}
                            for a, t, s, n in agent_steps],
            "ai": [{"capability": c, "calls": n, "avg_latency_ms": round(lat or 0), "tokens": int(t or 0),
                    "fallbacks": f, "validation_failures": v} for c, n, lat, t, f, v in ai]}


# ------------------------------------------------------------------ configuration & kill switches


@router.get("/config")
def config(actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    country, cv = get_config(db, "country:UG")
    weights, wv = get_config(db, "match_weights")
    from weza.domains.consent.service import current_template, template_history
    tpl = current_template(db)
    paths, pv = get_config(db, "question_paths:UG")
    return {"country": {"version": cv, "data": country}, "match_weights": {"version": wv, "data": weights},
            "flags": [{"key": k, "label": v, "enabled": (db.get(FeatureFlag, k).enabled if db.get(FeatureFlag, k)
                                                          else k == "channel.whatsapp_simulator")} for k, v in FLAGS.items()],
            "kill_switches": [{"key": k, "label": v, "value": (db.get(KillSwitch, k).value if db.get(KillSwitch, k) else {}),
                               "reason": (db.get(KillSwitch, k).reason if db.get(KillSwitch, k) else ""),
                               "updated_by": (db.get(KillSwitch, k).updated_by if db.get(KillSwitch, k) else None)}
                              for k, v in KILL_SWITCHES.items()],
            "consent_template": {"version": tpl.version, "title": tpl.title, "text": tpl.text, "hash": tpl.text_hash},
            "consent_history": [{"version": t.version, "status": t.status, "hash": t.text_hash,
                                 "effective_from": t.effective_from.isoformat()} for t in template_history(db)],
            "question_paths": {"version": pv, "data": paths},
            "can_edit": policy.has(actor, "admin.config")}


CHANNELS = ("web", "whatsapp", "sms")


def _validate_switch(key: str, value: dict) -> None:
    if key in ("pause_all_routing", "pause_billing_events"):
        if set(value) != {"on"} or not isinstance(value["on"], bool):
            raise ValidationFailed("Send {\"on\": true} or {\"on\": false}.")
    elif key == "ai_mode":
        if set(value) != {"mode"} or value["mode"] not in ("AVAILABLE", "DEGRADED", "UNAVAILABLE"):
            raise ValidationFailed("AI mode must be AVAILABLE, DEGRADED or UNAVAILABLE.")
    elif key == "disabled_channels":
        ch = value.get("channels")
        if set(value) != {"channels"} or not isinstance(ch, list) or any(c not in CHANNELS for c in ch)                 or len(set(ch)) != len(ch):
            raise ValidationFailed("Disabled channels must be a list drawn from web, whatsapp and sms.")


class SwitchIn(BaseModel):
    key: str
    value: dict
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/kill-switches")
def set_switch(body: SwitchIn, actor: Actor = W, db: Session = DB):
    """Audited network controls (TSD §75). Routing-affecting switches trigger market re-clearing."""
    if body.key not in KILL_SWITCHES:
        raise ValidationFailed("Unknown switch.")
    policy.require(actor, "admin.network_control" if body.key == "pause_all_routing" else "admin.config")
    require_step_up(actor)
    _validate_switch(body.key, body.value)
    row = db.get(KillSwitch, body.key) or KillSwitch(key=body.key)
    before = row.value
    row.value, row.reason, row.updated_by = body.value, body.reason, actor.display
    db.merge(row)
    audit(db, actor, "kill_switch.changed", "kill_switch", body.key, before=before, after=body.value, reason=body.reason)
    emit(db, "KillSwitchChanged", topic="audit", aggregate_type="kill_switch", aggregate_id=body.key,
         data={"value": body.value})
    return config(actor, db)


class FlagIn(BaseModel):
    key: str
    enabled: bool
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/flags")
def set_flag(body: FlagIn, actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.config")
    if body.key not in FLAGS:
        raise ValidationFailed("Unknown flag.")
    row = db.get(FeatureFlag, body.key)
    before = row.enabled if row else body.key == "channel.whatsapp_simulator"
    row = row or FeatureFlag(key=body.key, description=FLAGS[body.key])
    row.enabled = body.enabled
    db.merge(row)
    audit(db, actor, "flag.changed", "feature_flag", body.key, before={"enabled": before},
          after={"enabled": body.enabled}, reason=body.reason)
    emit(db, "ConfigChanged", topic="audit", aggregate_type="feature_flag", aggregate_id=body.key,
         data={"enabled": body.enabled})
    return config(actor, db)


class WeightsIn(BaseModel):
    weights: dict[str, float]
    note: str = Field(..., min_length=3, max_length=500)


@router.post("/config/match-weights")
def set_weights(body: WeightsIn, actor: Actor = W, db: Session = DB):
    """Composite weights are configurable and versioned (TSD §20)."""
    policy.require(actor, "admin.config")
    keys = {"product_fit", "appetite_fit", "preference_fit", "readiness", "capacity_fit"}
    if set(body.weights) != keys or abs(sum(body.weights.values()) - 1) > 0.001 or min(body.weights.values()) < 0:
        raise ValidationFailed("Provide all five weights, each ≥ 0, summing to 1.")
    row = publish_config(db, "match_weights", body.weights, actor.display, body.note)
    audit(db, actor, "config.match_weights", "config", f"match_weights:v{row.version}", after=body.weights,
          reason=body.note)
    emit(db, "KillSwitchChanged", topic="audit", aggregate_type="config", aggregate_id="match_weights",
         data={"version": row.version})
    return config(actor, db)


class ConsentTemplateIn(BaseModel):
    title: str = Field(..., min_length=3, max_length=160)
    text: str = Field(..., min_length=50, max_length=10000)
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/config/consent-template")
def publish_consent_template(body: ConsentTemplateIn, actor: Actor = W, db: Session = DB):
    """Versioned legal text (TSD §71–72): written by a person, never by AI; publishing retires the previous version."""
    policy.require(actor, "admin.config")
    from weza.domains.consent.service import publish_template
    tpl = publish_template(db, actor, title=body.title, text=body.text, reason=body.reason)
    emit(db, "ConfigChanged", topic="audit", aggregate_type="consent_template", aggregate_id=tpl.id,
         data={"version": tpl.version, "text_hash": tpl.text_hash})
    return config(actor, db)


@router.get("/users")
def weza_users(actor: Actor = W, db: Session = DB):
    policy.require(actor, "admin.read")
    rows = db.execute(select(User).where(or_(User.kind == "WEZA"))).scalars()
    return {"users": [{"id": str(u.id), "name": u.full_name, "email": u.email, "roles": u.weza_roles,
                       "mfa_enrolled": u.mfa_enrolled} for u in rows]}


# ------------------------------------------------------------------ WhatsApp: connect the business number (coexistence)


@router.get("/whatsapp/embedded-signup")
def whatsapp_signup_config(actor: Actor = W):
    """Launch settings for Embedded Signup (Tech Provider onboarding of the WhatsApp Business app number)."""
    policy.require(actor, "admin.config")
    from weza.domains.notification import whatsapp_onboarding
    return whatsapp_onboarding.launch_config()


class SignupIn(BaseModel):
    code: str = Field(..., min_length=10, max_length=2048)
    waba_id: str | None = Field(None, max_length=32)
    event: str | None = Field(None, max_length=64)


@router.post("/whatsapp/embedded-signup")
def whatsapp_signup_connect(body: SignupIn, actor: Actor = W, db: Session = DB):
    """Exchange the Embedded Signup code (valid ~30 s), subscribe this app to the WABA, report the number's status."""
    policy.require(actor, "admin.config")
    require_step_up(actor)
    from weza.domains.notification import whatsapp_onboarding
    rate_limit(db, f"es:{actor.id}", 10, 3600)
    return whatsapp_onboarding.connect(db, actor, code=body.code, waba_id=body.waba_id or None, event=body.event)
