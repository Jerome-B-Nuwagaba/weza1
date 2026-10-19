"""Commercial engine (FSD §39–40, TSD §43–46; blueprint L3). Contract-configurable, idempotent, append-only."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.commercial.models import Attribution, CommercialEvent, Contract, Dispute
from weza.domains.customer.models import Customer
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity.models import Opportunity
from weza.domains.trust.service import audit
from weza.platform.context import Actor
from weza.platform.controls import StateMachine, billing_paused
from weza.platform.db import utcnow
from weza.platform.errors import NotFound, ValidationFailed
from weza.platform.events import emit

DISPUTE_REASONS = {
    "DUPLICATE": "Duplicate", "UNREACHABLE": "Unreachable", "INCORRECT_INFORMATION": "Incorrect information",
    "NO_CONSENT": "No consent / customer denial", "OUTSIDE_CRITERIA": "Outside agreed criteria",
    "EXISTING_CUSTOMER": "Existing customer", "OTHER": "Other",
}
DISPUTE_SM = StateMachine("Dispute", {
    "OPEN": {"UNDER_REVIEW"}, "UNDER_REVIEW": {"FURTHER_INVESTIGATION", "DECIDED"},
    "FURTHER_INVESTIGATION": {"UNDER_REVIEW", "DECIDED"}, "DECIDED": {"CLOSED"},
})
DEFAULT_DEFINITION = {"min_verification": "PHONE", "min_match_score": 60, "require_consent": True,
                      "require_routing": True, "exclude_synthetic": True}


def record_attribution(db: Session, *, source: str | None, campaign: str | None, partner: str | None,
                       referral: str | None, channel: str, landing: str | None) -> Attribution:
    a = Attribution(source=(source or "direct")[:40], campaign_code=(campaign or None), partner_code=(partner or None),
                    referral_code=referral, channel=channel, landing=(landing or "")[:200] or None)
    db.add(a)
    db.flush()
    return a


def active_contract(db: Session, institution_id: uuid.UUID) -> Contract | None:
    today = date.today()
    return db.execute(select(Contract).where(Contract.institution_id == institution_id, Contract.status == "ACTIVE",
                                             Contract.effective_from <= today)
                      .order_by(Contract.effective_from.desc()).limit(1)).scalar_one_or_none()


def on_opportunity_routed(db: Session, opp: Opportunity) -> CommercialEvent:
    """Billing eligibility per contract definition (FSD-BIL-001, BR-009). Idempotent per opportunity."""
    key = f"{opp.id}:QUALIFIED_OPPORTUNITY"
    existing = db.execute(select(CommercialEvent).where(CommercialEvent.idempotency_key == key)).scalar_one_or_none()
    if existing:
        return existing
    contract = active_contract(db, opp.institution_id)
    definition = {**DEFAULT_DEFINITION, **((contract.qualified_definition if contract else {}) or {})}
    customer = db.get(Customer, opp.customer_id)
    need = db.get(FinancialNeed, opp.need_id)
    checks = {
        "contract_active": contract is not None,
        "verification": customer is not None and customer.verification_level in ("PHONE", "IDENTITY"),
        "intent_established": need is not None and need.intent_confirmed_at is not None,
        "match_threshold": opp.match_score >= definition["min_match_score"],
        "consent": True,
        "routed": opp.state not in ("QUALIFIED", "ROUTING_FAILED"),
        # Sandbox (synthetic) customers never become opportunities, so they can never reach billing (TSD §74).
        "not_synthetic": True,
    }
    window = contract.duplicate_window_days if contract else 30
    prior = db.execute(select(func.count()).select_from(CommercialEvent).join(
        Opportunity, Opportunity.id == CommercialEvent.opportunity_id).where(
        Opportunity.customer_id == opp.customer_id, Opportunity.institution_id == opp.institution_id,
        CommercialEvent.kind == "QUALIFIED_OPPORTUNITY", CommercialEvent.status.in_(["BILLABLE", "INCLUDED_IN_PLAN"]),
        CommercialEvent.created_at >= utcnow() - timedelta(days=window))).scalar_one()
    checks["not_duplicate"] = prior == 0
    period = utcnow().strftime("%Y-%m")
    attribution = {}
    if opp.attribution_id:
        a = db.get(Attribution, opp.attribution_id)
        if a:
            attribution = {"source": a.source, "campaign": a.campaign_code, "partner": a.partner_code, "channel": a.channel}
    if billing_paused(db):
        status, amount = "HELD", Decimal(0)
    elif all(checks.values()):
        used = db.execute(select(func.count()).select_from(CommercialEvent).where(
            CommercialEvent.institution_id == opp.institution_id, CommercialEvent.billing_period == period,
            CommercialEvent.status == "INCLUDED_IN_PLAN")).scalar_one()
        if contract and used < contract.included_opportunities:
            status, amount = "INCLUDED_IN_PLAN", Decimal(0)
        else:
            status, amount = "BILLABLE", Decimal(contract.opportunity_price if contract else 0)
    else:
        status, amount = "NOT_BILLABLE", Decimal(0)
    ev = CommercialEvent(idempotency_key=key, institution_id=opp.institution_id, opportunity_id=opp.id,
                         contract_id=contract.id if contract else None, kind="QUALIFIED_OPPORTUNITY", amount=amount,
                         currency=contract.currency if contract else "UGX", status=status, billing_period=period,
                         evaluation={"checks": checks, "definition": definition}, attribution=attribution)
    db.add(ev)
    db.flush()
    emit(db, "CommercialEventCreated", topic="commercial", aggregate_type="commercial_event", aggregate_id=ev.id,
         institution_id=opp.institution_id, data={"status": status, "amount": str(amount)})
    return ev


def open_dispute(db: Session, actor: Actor, event_id: uuid.UUID, reason: str, description: str) -> Dispute:
    query = select(CommercialEvent).where(CommercialEvent.id == event_id)
    if not actor.is_weza:
        query = query.where(CommercialEvent.institution_id == actor.institution_id)
    ev = db.execute(query).scalar_one_or_none()
    if ev is None or (not actor.is_weza and ev.institution_id != actor.institution_id):
        raise NotFound("Not found.")
    if reason not in DISPUTE_REASONS:
        raise ValidationFailed("Choose a dispute reason.")
    if ev.status not in ("BILLABLE", "INCLUDED_IN_PLAN"):
        raise ValidationFailed("Only billed opportunities can be disputed.")
    contract = db.get(Contract, ev.contract_id) if ev.contract_id else None
    window = contract.dispute_window_days if contract else 14
    if ev.created_at < utcnow() - timedelta(days=window):
        raise ValidationFailed(f"The dispute window ({window} days) has passed.", code="DISPUTE_WINDOW_CLOSED")
    existing = db.execute(select(Dispute).where(Dispute.commercial_event_id == ev.id)).scalar_one_or_none()
    if existing:
        return existing
    d = Dispute(commercial_event_id=ev.id, institution_id=ev.institution_id, opportunity_id=ev.opportunity_id,
                reason=reason, description=description[:4000], state="OPEN",
                history=[{"at": utcnow().isoformat(), "state": "OPEN", "by": actor.display}])
    db.add(d)
    ev.status = "DISPUTED"
    db.flush()
    audit(db, actor, "billing.dispute_opened", "dispute", d.id, institution_id=ev.institution_id,
          after={"reason": reason})
    emit(db, "DisputeOpened", topic="commercial", aggregate_type="dispute", aggregate_id=d.id,
         institution_id=ev.institution_id, data={"reason": reason})
    return d


def move_dispute(db: Session, actor: Actor, dispute_id: uuid.UUID, to_state: str, note: str = "",
                 decision: str | None = None) -> Dispute:
    d = db.get(Dispute, dispute_id)
    if d is None:
        raise NotFound("Not found.")
    DISPUTE_SM.check(d.state, to_state)
    ev = db.get(CommercialEvent, d.commercial_event_id)
    if to_state == "DECIDED":
        if decision not in ("CHARGE_VALID", "CHARGE_REVERSED", "OPPORTUNITY_REPLACED"):
            raise ValidationFailed("Choose a decision.")
        d.decision, d.decision_note, d.decided_by, d.decided_at = decision, note, actor.id, utcnow()
        if decision == "CHARGE_VALID":
            ev.status = "BILLABLE" if Decimal(ev.amount) > 0 else "INCLUDED_IN_PLAN"
        else:
            ev.status = "REVERSED"
            kind = "REVERSAL" if decision == "CHARGE_REVERSED" else "CREDIT"
            db.add(CommercialEvent(idempotency_key=f"{ev.id}:{kind}", institution_id=ev.institution_id,
                                   opportunity_id=ev.opportunity_id, contract_id=ev.contract_id, kind=kind,
                                   amount=-Decimal(ev.amount), currency=ev.currency, status=kind,
                                   billing_period=utcnow().strftime("%Y-%m"), reverses_event_id=ev.id,
                                   evaluation={"dispute_id": str(d.id), "decision": decision}))
    d.state = to_state
    d.history = [*d.history, {"at": utcnow().isoformat(), "state": to_state, "by": actor.display, "note": note,
                              "decision": decision}]
    audit(db, actor, "billing.dispute_" + to_state.lower(), "dispute", d.id, institution_id=d.institution_id,
          after={"state": to_state, "decision": decision}, reason=note)
    if to_state == "DECIDED":
        emit(db, "DisputeDecided", topic="commercial", aggregate_type="dispute", aggregate_id=d.id,
             institution_id=d.institution_id, data={"decision": decision})
    return d


def statement(db: Session, institution_id: uuid.UUID, period: str | None = None) -> dict:
    period = period or utcnow().strftime("%Y-%m")
    rows = db.execute(select(CommercialEvent).where(CommercialEvent.institution_id == institution_id,
                                                    CommercialEvent.billing_period == period)).scalars().all()
    contract = active_contract(db, institution_id)
    billable = sum(Decimal(r.amount) for r in rows if r.status in ("BILLABLE",))
    adjustments = sum(Decimal(r.amount) for r in rows if r.kind in ("REVERSAL", "CREDIT"))
    return {"period": period, "plan": contract.plan if contract else None,
            "subscription_fee": float(contract.subscription_fee) if contract else 0,
            "included_opportunities": contract.included_opportunities if contract else 0,
            "included_used": sum(1 for r in rows if r.status == "INCLUDED_IN_PLAN"),
            "billable_count": sum(1 for r in rows if r.status == "BILLABLE"),
            "billable_amount": float(billable), "adjustments": float(adjustments),
            "total_due": float((Decimal(contract.subscription_fee) if contract else 0) + billable + adjustments),
            "currency": contract.currency if contract else "UGX"}
