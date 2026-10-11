"""Qualified Opportunity saga, routing, assignment, lifecycle, outcomes, freshness and service targets
(FSD §14–15, §25–27, §37; TSD §30–33; blueprint G3)."""

import secrets
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.admin_config import get_config
from weza.domains.appetite.models import Appetite, AppetiteVersion
from weza.domains.consent.models import Consent
from weza.domains.customer.models import Customer, Document, ProfileSnapshot
from weza.domains.customer.service import current_facts
from weza.domains.identity import service as identity
from weza.domains.institution.models import Institution, RoutingRule, ServiceTarget, Team
from weza.domains.integrity import service as integrity
from weza.domains.matching.engine import consume_capacity
from weza.domains.matching.models import Match
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity.models import Activity, Assignment, Opportunity, Outcome
from weza.domains.product.models import Product, ProductVersion
from weza.domains.trust import policy
from weza.domains.trust.service import audit, record_decision
from weza.platform.context import SYSTEM, Actor
from weza.platform.controls import StateMachine, routing_paused
from weza.platform.db import utcnow
from weza.platform.errors import Conflict, NotFound, ValidationFailed
from weza.platform.events import emit

TERMINAL = {"CLOSED", "WITHDRAWN", "EXPIRED", "ROUTING_FAILED"}
OPEN_STATES = {"QUALIFIED", "ROUTED", "RECEIVED", "ASSIGNED", "CONTACTED", "PROCEEDING", "SUBMITTED_TO_INSTITUTION",
               "REPORTED_APPROVED"}
INSTITUTION_FORWARD = ["RECEIVED", "ASSIGNED", "CONTACTED", "PROCEEDING", "SUBMITTED_TO_INSTITUTION"]

OPP_SM = StateMachine("Opportunity", {
    "QUALIFIED": {"ROUTED", "ROUTING_FAILED", "CLOSED", "WITHDRAWN"},
    "ROUTED": {"RECEIVED", "ASSIGNED", "CONTACTED", "WITHDRAWN", "EXPIRED", "CLOSED"},
    "RECEIVED": {"ASSIGNED", "CONTACTED", "WITHDRAWN", "EXPIRED", "CLOSED"},
    "ASSIGNED": {"CONTACTED", "PROCEEDING", "WITHDRAWN", "EXPIRED", "CLOSED", "REPORTED_DECLINED"},
    "CONTACTED": {"PROCEEDING", "SUBMITTED_TO_INSTITUTION", "REPORTED_APPROVED", "REPORTED_DECLINED", "WITHDRAWN",
                  "EXPIRED", "CLOSED"},
    "PROCEEDING": {"SUBMITTED_TO_INSTITUTION", "REPORTED_APPROVED", "REPORTED_DECLINED", "WITHDRAWN", "EXPIRED",
                   "CLOSED"},
    "SUBMITTED_TO_INSTITUTION": {"REPORTED_APPROVED", "REPORTED_DECLINED", "WITHDRAWN", "CLOSED"},
    "REPORTED_APPROVED": {"REPORTED_DISBURSED", "WITHDRAWN", "CLOSED"},
    "REPORTED_DISBURSED": {"CLOSED"},
    "REPORTED_DECLINED": {"REMATCH_ELIGIBLE", "CLOSED"},
    "REMATCH_ELIGIBLE": {"CLOSED"},
})

DECLINE_REASONS = {
    "ELIGIBILITY": "Eligibility", "AFFORDABILITY": "Affordability", "DOCUMENTATION": "Documentation",
    "CREDIT_HISTORY": "Credit history", "INCOME_TURNOVER": "Income / turnover", "COLLATERAL": "Collateral",
    "CUSTOMER_WITHDREW": "Customer withdrew", "APPETITE_CHANGED": "Appetite changed", "UNREACHABLE": "Customer unreachable",
    "OTHER": "Other",
}


class RematchRequired(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _reference(db: Session) -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    for _ in range(10):
        ref = "OPP-" + "".join(secrets.choice(alphabet) for _ in range(5))
        if not db.execute(select(Opportunity.id).where(Opportunity.reference == ref)).first():
            return ref
    raise Conflict("Could not allocate reference.")


def _log(db: Session, opp: Opportunity, kind: str, actor: Actor, note: str | None = None, data: dict | None = None):
    db.add(Activity(opportunity_id=opp.id, kind=kind, actor=actor.display or actor.kind, note=note, data=data or {}))
    opp.last_activity_at = utcnow()
    if opp.freshness != "FRESH" and opp.state not in TERMINAL:
        opp.freshness = "FRESH"


def validate_match(db: Session, match: Match) -> tuple[Institution, Product, ProductVersion, Appetite | None]:
    """Never use a stale match just because it exists (Skill §21)."""
    now = utcnow()
    if match.state not in ("RANKED", "PRESENTED", "SELECTED"):
        raise RematchRequired(f"match_{match.state.lower()}")
    if match.expires_at and match.expires_at <= now:
        match.state = "EXPIRED"
        raise RematchRequired("match_expired")
    if match.readiness != "READY":
        raise ValidationFailed("Please complete the outstanding items for this option first.", code="MATCH_NOT_READY")
    if routing_paused(db):
        raise RematchRequired("routing_paused")
    inst = db.get(Institution, match.institution_id)
    prod = db.get(Product, match.product_id)
    if inst is None or inst.status != "ACTIVE":
        raise RematchRequired("institution_inactive")
    if prod is None or prod.status != "ACTIVE" or prod.active_version_id != match.product_version_id:
        raise RematchRequired("product_changed")
    ap = db.get(Appetite, match.appetite_id) if match.appetite_id else None
    if ap is not None and (ap.lifecycle_status != "ACTIVE" or ap.active_version_id != match.appetite_version_id
                           or ap.capacity_state in ("FULL", "PAUSED")):
        raise RematchRequired("appetite_changed")
    return inst, prod, db.get(ProductVersion, match.product_version_id), ap


def qualify(db: Session, actor: Actor, need: FinancialNeed, match: Match, consent: Consent,
            routing_strategy: str = "CUSTOMER_SELECTED") -> Opportunity:
    """Validate Match → Validate Consent → Check Duplicate/Integrity → Create Opportunity → Route.
    Runs in the caller's transaction with the outbox, so it is all-or-nothing (TSD §32, §55).
    Assignment, notification and billing follow as idempotent consumers of OpportunityRouted."""
    key = f"{need.id}:{match.id}"
    existing = db.execute(select(Opportunity).where(Opportunity.idempotency_key == key)).scalar_one_or_none()
    if existing:
        return existing
    inst, prod, pv, ap = validate_match(db, match)
    if consent.status != "GRANTED" or consent.institution_id != inst.id or consent.match_id != match.id:
        raise ValidationFailed("Consent is required before sharing.", code="CONSENT_REQUIRED")
    customer = db.get(Customer, need.customer_id)
    if customer is None or customer.verification_level == "NONE":
        raise ValidationFailed("Phone verification is required.", code="VERIFICATION_REQUIRED")
    if need.intent_confirmed_at is None:
        raise ValidationFailed("Please confirm your request first.", code="INTENT_NOT_CONFIRMED")
    active_for_need = db.execute(select(func.count()).select_from(Opportunity).where(
        Opportunity.need_id == need.id, Opportunity.state.in_(OPEN_STATES))).scalar_one()
    if active_for_need >= 3:
        raise ValidationFailed("You can share one request with up to 3 institutions at a time.",
                               code="MULTI_OPTION_LIMIT")

    # Duplicate check under the institution's contract duplicate window (FSD-INTG-001)
    from weza.domains.commercial.service import active_contract
    contract = active_contract(db, inst.id)
    window = contract.duplicate_window_days if contract else 30
    dup = db.execute(select(Opportunity).where(
        Opportunity.customer_id == customer.id, Opportunity.institution_id == inst.id,
        Opportunity.state.in_(OPEN_STATES | {"REPORTED_DISBURSED"}),
        Opportunity.purpose_category == need.purpose_category,
        Opportunity.qualified_at >= utcnow() - timedelta(days=window))).scalars().first()
    risk, signals = integrity.evaluate_customer(db, customer, need)
    if risk == "BLOCKED":
        raise ValidationFailed("We can't submit this request right now. Our team will be in touch.",
                               code="INTEGRITY_BLOCKED")

    snap = db.get(ProfileSnapshot, match.profile_snapshot_id) if match.profile_snapshot_id else None
    av = db.get(AppetiteVersion, match.appetite_version_id) if match.appetite_version_id else None
    hold = dup is not None or risk in ("REVIEW", "HIGH_RISK")
    opp = Opportunity(
        reference=_reference(db), idempotency_key=key, need_id=need.id, customer_id=customer.id,
        institution_id=inst.id, product_id=prod.id, appetite_id=ap.id if ap else None, match_id=match.id,
        consent_id=consent.id, state="QUALIFIED", routing_strategy=routing_strategy, amount=need.amount,
        match_score=match.score, quality_score=need.quality_score or 0, sector=need.sector,
        district=(match.explanation or {}).get("district") or _district(db, customer.id, need),
        customer_type=need.customer_type, purpose_category=need.purpose_category,
        attribution_id=need.attribution_id or customer.attribution_id, integrity_hold=hold, is_demo=need.is_demo,
        priority=_priority(match.score, need.amount),
        snapshot={
            "profile_snapshot": {"id": str(snap.id), "version": snap.version, "hash": snap.hash} if snap else None,
            "need": {"amount": str(need.amount), "currency": need.currency, "purpose": need.purpose,
                     "purpose_category": need.purpose_category, "customer_type": need.customer_type,
                     "sector": need.sector, "tenor_months": need.tenor_months},
            "product_version": {"id": str(pv.id), "version": pv.version, "name": pv.name, "terms": pv.terms,
                                "ruleset_hash": pv.ruleset_hash},
            "appetite_version": {"id": str(av.id), "version": av.version, "min_match_score": av.min_match_score}
            if av else None,
            "match": {"id": str(match.id), "score": match.score, "components": match.components,
                      "explanation": match.explanation, "algorithm_version": match.algorithm_version,
                      "weights_version": match.weights_version, "ruleset_hash": match.ruleset_hash},
            "quality": {"score": need.quality_score, "factors": need.quality_factors},
            "consent": {"id": str(consent.id), "version": consent.template_version, "categories": consent.data_categories,
                        "text_hash": consent.text_hash, "granted_at": consent.granted_at.isoformat()},
            "integrity": {"state": risk, "signals": [s["kind"] for s in signals]},
        })
    db.add(opp)
    db.flush()
    consent.opportunity_id = opp.id
    match.state = "SELECTED"
    match.selected_at = match.selected_at or utcnow()
    need.status = "SUBMITTED"
    if ap is not None:
        consume_capacity(db, ap.id, Decimal(need.amount or 0))
    _log(db, opp, "QUALIFIED", actor, data={"score": match.score})
    record_decision(db, "QUALIFICATION", "opportunity", opp.id, inputs={"need": str(need.id), "match": str(match.id),
                    "consent": str(consent.id)}, output={"hold": hold, "duplicate_of": str(dup.id) if dup else None,
                                                         "integrity": risk},
                    ruleset_version=match.ruleset_hash, algorithm_version=match.algorithm_version)
    audit(db, actor, "opportunity.qualified", "opportunity", opp.id, institution_id=inst.id,
          after={"reference": opp.reference, "hold": hold})
    emit(db, "OpportunityQualified", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
         institution_id=inst.id, data={"reference": opp.reference, "hold": hold})
    if dup is not None:
        integrity.add_review(db, "DUPLICATE_HOLD", f"Possible duplicate of {dup.reference}", "opportunity", opp.id,
                             detail={"duplicate_of": dup.reference, "institution": inst.display_name}, due_hours=48)
    elif risk in ("REVIEW", "HIGH_RISK"):
        integrity.open_case(db, "opportunity", opp.id, risk, signals, {"reference": opp.reference})
    else:
        route(db, opp)
    return opp


def _district(db: Session, customer_id, need) -> str | None:
    facts = current_facts(db, customer_id)
    for k in ("business.district", "residence.district", "farm.district"):
        if k in facts:
            return facts[k].value.get("v")
    return need.district


def _priority(score: float, amount) -> str:
    high_value = Decimal(amount or 0) >= Decimal(50_000_000)
    if score >= 90 and high_value:
        return "URGENT"
    if score >= 90 or high_value:
        return "HIGH"
    return "NORMAL"


def route(db: Session, opp: Opportunity, actor: Actor = SYSTEM) -> None:
    """Make the opportunity visible in the institution workspace. Customer data stays behind the Disclosure
    Gateway; if the institution became ineligible, compensate (FSD-OPP-005)."""
    inst = db.get(Institution, opp.institution_id)
    if inst is None or inst.status != "ACTIVE" or routing_paused(db):
        OPP_SM.check(opp.state, "ROUTING_FAILED")
        opp.state = "ROUTING_FAILED"
        need = db.get(FinancialNeed, opp.need_id)
        need.status = "READY_FOR_MATCHING"
        _log(db, opp, "ROUTING_FAILED", actor, note="Institution not available; customer data not shared.")
        emit(db, "OpportunityRoutingFailed", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
             institution_id=opp.institution_id, data={"need_id": str(opp.need_id)})
        return
    OPP_SM.check(opp.state, "ROUTED")
    opp.state = "ROUTED"
    opp.routed_at = utcnow()
    opp.integrity_hold = False
    _log(db, opp, "ROUTED", actor)
    emit(db, "OpportunityRouted", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
         institution_id=opp.institution_id, data={"reference": opp.reference, "priority": opp.priority,
                                                  "amount": str(opp.amount), "score": opp.match_score})


# ------------------------------------------------------------------ assignment & service targets


def _rule_matches(rule: RoutingRule, opp: Opportunity) -> bool:
    c = rule.conditions or {}
    if c.get("product_ids") and str(opp.product_id) not in {str(x) for x in c["product_ids"]}:
        return False
    if c.get("customer_types") and opp.customer_type not in c["customer_types"]:
        return False
    if c.get("sectors") and opp.sector not in c["sectors"]:
        return False
    if c.get("regions"):
        from weza.domains.admin_config import region_of
        if region_of(opp.district) not in c["regions"]:
            return False
    if c.get("min_amount") is not None and Decimal(opp.amount) < Decimal(str(c["min_amount"])):
        return False
    if c.get("max_amount") is not None and Decimal(opp.amount) > Decimal(str(c["max_amount"])):
        return False
    return True


def assign_by_rules(db: Session, opp: Opportunity) -> Assignment:
    """FSD-ASG-001/002: rule-based assignment; least-loaded officer within the team; else Unassigned."""
    existing = db.get(Assignment, opp.id)
    if existing is not None:
        return existing
    st = db.get(ServiceTarget, opp.institution_id) or ServiceTarget(institution_id=opp.institution_id)
    base = opp.routed_at or utcnow()
    a = Assignment(opportunity_id=opp.id, institution_id=opp.institution_id,
                   first_contact_due_at=base + timedelta(minutes=st.first_contact_within_minutes or 1440))
    rules = db.execute(select(RoutingRule).where(RoutingRule.institution_id == opp.institution_id,
                                                 RoutingRule.active.is_(True)).order_by(RoutingRule.priority)).scalars()
    chosen = next((r for r in rules if _rule_matches(r, opp)), None)
    if chosen is not None:
        a.rule_id, a.team_id = chosen.id, chosen.target_team_id
        a.user_id = chosen.target_user_id or (_least_loaded_officer(db, opp.institution_id, chosen.target_team_id)
                                             if chosen.target_team_id else None)
    if a.user_id:
        a.assigned_at, a.assigned_by = utcnow(), "RULE"
        a.ack_due_at = utcnow() + timedelta(minutes=st.ack_within_minutes or 120)
        if opp.state in ("ROUTED", "RECEIVED"):
            OPP_SM.check(opp.state, "ASSIGNED")
            opp.state = "ASSIGNED"
    else:
        a.assigned_by = "UNASSIGNED"
    db.add(a)
    db.flush()
    _log(db, opp, "ASSIGNED" if a.user_id else "UNASSIGNED", SYSTEM,
         note=f"Rule: {chosen.name}" if chosen else "No routing rule matched — waiting in Unassigned queue")
    record_decision(db, "ASSIGNMENT", "opportunity", opp.id, inputs={"rules_evaluated": True},
                    output={"rule": str(chosen.id) if chosen else None, "user": str(a.user_id) if a.user_id else None,
                            "team": str(a.team_id) if a.team_id else None}, algorithm_version="assign_v1")
    emit(db, "OpportunityAssigned" if a.user_id else "OpportunityUnassigned", topic="opportunity",
         aggregate_type="opportunity", aggregate_id=opp.id, institution_id=opp.institution_id,
         data={"user_id": str(a.user_id) if a.user_id else None, "team_id": str(a.team_id) if a.team_id else None,
               "reference": opp.reference, "priority": opp.priority})
    return a


def _least_loaded_officer(db: Session, institution_id, team_id) -> uuid.UUID | None:
    from weza.domains.identity.models import Membership, User
    officers = db.execute(select(Membership.user_id).join(User, User.id == Membership.user_id).where(
        Membership.institution_id == institution_id, Membership.team_id == team_id, User.status == "ACTIVE",
        Membership.roles.contains(["OFFICER"]))).scalars().all()
    if not officers:
        return None
    loads = dict(db.execute(select(Assignment.user_id, func.count()).join(
        Opportunity, Opportunity.id == Assignment.opportunity_id).where(
        Assignment.user_id.in_(officers), Opportunity.state.in_(OPEN_STATES)).group_by(Assignment.user_id)).all())
    return min(officers, key=lambda u: (loads.get(u, 0), str(u)))


def assign_manual(db: Session, actor: Actor, opp: Opportunity, user_id: uuid.UUID, reason: str | None = None) -> Assignment:
    from weza.domains.identity.models import Membership
    policy.require(actor, "opportunity.assign")
    policy.require_tenant(actor, opp.institution_id)
    m = db.execute(select(Membership).where(Membership.user_id == user_id)).scalar_one_or_none()
    if m is None or m.institution_id != opp.institution_id:
        raise ValidationFailed("That person is not in your institution.")
    a = db.get(Assignment, opp.id)
    st = db.get(ServiceTarget, opp.institution_id) or ServiceTarget(institution_id=opp.institution_id)
    before = str(a.user_id) if a and a.user_id else None
    if a is None:
        a = Assignment(opportunity_id=opp.id, institution_id=opp.institution_id,
                       first_contact_due_at=(opp.routed_at or utcnow()) + timedelta(minutes=st.first_contact_within_minutes))
        db.add(a)
    a.user_id, a.team_id, a.assigned_by, a.assigned_at = user_id, m.team_id, "USER", utcnow()
    a.ack_due_at, a.acked_at = utcnow() + timedelta(minutes=st.ack_within_minutes), None
    if opp.state in ("ROUTED", "RECEIVED"):
        opp.state = "ASSIGNED"
    _log(db, opp, "REASSIGNED" if before else "ASSIGNED", actor, note=reason)
    audit(db, actor, "opportunity.assigned", "opportunity", opp.id, before={"user": before}, after={"user": str(user_id)},
          reason=reason)
    emit(db, "OpportunityAssigned", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
         institution_id=opp.institution_id, data={"user_id": str(user_id), "reference": opp.reference,
                                                  "priority": opp.priority, "manual": True})
    return a


# ------------------------------------------------------------------ lifecycle


def mark_received(db: Session, actor: Actor, opp: Opportunity) -> None:
    if opp.received_at is None and actor.is_institution:
        opp.received_at = utcnow()
        if opp.state == "ROUTED":
            opp.state = "RECEIVED"
        emit(db, "OpportunityReceived", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
             institution_id=opp.institution_id, data={})
    a = db.get(Assignment, opp.id)
    if a and a.user_id == actor.id and a.acked_at is None:
        a.acked_at = utcnow()


def update_status(db: Session, actor: Actor, opp: Opportunity, to_state: str, note: str | None = None) -> Opportunity:
    policy.require(actor, "opportunity.update_status")
    policy.require_tenant(actor, opp.institution_id)
    a = db.get(Assignment, opp.id)
    if "MANAGER" not in actor.roles and (a is None or a.user_id != actor.id):
        raise ValidationFailed("Only the assigned officer or a manager can update this opportunity.",
                               code="NOT_ASSIGNEE")
    if to_state not in INSTITUTION_FORWARD + ["CLOSED"]:
        raise ValidationFailed("Use the outcome action for approvals, declines and disbursements.")
    if opp.integrity_hold:
        raise ValidationFailed("This opportunity is on hold pending WEZA checks.", code="ON_HOLD")
    _advance_to(db, actor, opp, to_state, note)
    if to_state == "CONTACTED" and a is not None and a.first_contact_at is None:
        a.first_contact_at = utcnow()
        a.breach_state = "MET"
    return opp


def _advance_to(db: Session, actor: Actor, opp: Opportunity, to_state: str, note: str | None) -> None:
    """Officers may skip intermediate forward states (e.g. ROUTED → CONTACTED) but never move backwards."""
    if opp.state == to_state:
        return
    path = ["ROUTED", "RECEIVED", "ASSIGNED", "CONTACTED", "PROCEEDING", "SUBMITTED_TO_INSTITUTION"]
    if opp.state in path and to_state in path and path.index(to_state) > path.index(opp.state):
        before = opp.state
        opp.state = to_state
    else:
        OPP_SM.check(opp.state, to_state)
        before, opp.state = opp.state, to_state
    if to_state in TERMINAL:
        opp.closed_at = utcnow()
    _log(db, opp, to_state, actor, note=note)
    audit(db, actor, "opportunity.status", "opportunity", opp.id, before={"state": before}, after={"state": to_state},
          reason=note)
    emit(db, "OpportunityStatusChanged", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
         institution_id=opp.institution_id, data={"from": before, "to": to_state, "reference": opp.reference})


def report_outcome(db: Session, actor: Actor, opp: Opportunity, *, state: str, reason_category: str | None = None,
                   reason_note: str | None = None, approved_amount=None, disbursed_amount=None, disbursed_on=None) -> Outcome:
    """Lightweight institution-reported outcome (FSD §27, BR-005)."""
    policy.require(actor, "opportunity.update_status")
    policy.require_tenant(actor, opp.institution_id)
    if state not in ("REPORTED_APPROVED", "REPORTED_DECLINED", "REPORTED_DISBURSED", "WITHDRAWN"):
        raise ValidationFailed("Unknown outcome.")
    if state == "REPORTED_DECLINED" and reason_category not in DECLINE_REASONS:
        raise ValidationFailed("Please choose a decline reason.", code="REASON_REQUIRED")
    if state == "REPORTED_DISBURSED" and not disbursed_amount:
        raise ValidationFailed("Please enter the disbursed amount.", code="AMOUNT_REQUIRED")
    if state == "REPORTED_DISBURSED" and opp.state != "REPORTED_APPROVED":
        _advance_to(db, actor, opp, "REPORTED_APPROVED", "Implied by reported disbursement")
    if opp.state in ("ROUTED", "RECEIVED", "ASSIGNED") and state in ("REPORTED_APPROVED", "REPORTED_DECLINED"):
        _advance_to(db, actor, opp, "CONTACTED", "Implied by reported outcome")
        a = db.get(Assignment, opp.id)
        if a and a.first_contact_at is None:
            a.first_contact_at, a.breach_state = utcnow(), "MET"
    _advance_to(db, actor, opp, state, reason_note)
    out = Outcome(opportunity_id=opp.id, institution_id=opp.institution_id, state=state, reason_category=reason_category,
                  reason_note=reason_note, approved_amount=approved_amount, disbursed_amount=disbursed_amount,
                  disbursed_on=disbursed_on, reported_by=actor.id)
    db.add(out)
    db.flush()
    emit(db, "OutcomeReported", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
         institution_id=opp.institution_id, data={"state": state, "reason": reason_category,
                                                  "reference": opp.reference,
                                                  "approved_amount": str(approved_amount) if approved_amount else None,
                                                  "disbursed_amount": str(disbursed_amount) if disbursed_amount else None})
    return out


def customer_withdraw(db: Session, actor: Actor, opp: Opportunity, reason: str | None = None) -> None:
    if opp.state in TERMINAL or opp.state in ("REPORTED_DISBURSED",):
        raise ValidationFailed("This request can no longer be withdrawn.")
    _advance_to(db, actor, opp, "WITHDRAWN", reason or "Customer withdrew")
    emit(db, "OpportunityWithdrawn", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
         institution_id=opp.institution_id, data={"reference": opp.reference})


# ------------------------------------------------------------------ Opportunity 360 via the Disclosure Gateway


def view(db: Session, actor: Actor, opp_id: uuid.UUID) -> dict:
    opp = db.get(Opportunity, opp_id)
    if opp is None:
        raise NotFound("Not found.")
    policy.require(actor, "opportunity.read_meta")
    policy.require_tenant(actor, opp.institution_id)
    a = db.get(Assignment, opp.id)
    consent = db.get(Consent, opp.consent_id)
    decision = policy.decide_opportunity_access(db, actor, opp, a, consent)
    if decision.result == "DENY":
        raise NotFound("Not found.")
    mark_received(db, actor, opp)
    customer_block: dict = {"restricted": decision.result != "PERMIT", "restriction_reason": decision.reason,
                            "fields": {}}
    if decision.result == "PERMIT":
        cust = db.get(Customer, opp.customer_id)
        vault = identity.vault_read(db, cust.vault_token)
        facts = {k: f.value.get("v") for k, f in current_facts(db, opp.customer_id).items()}
        available = {
            "full_name": vault.get("full_name"), "phone": vault.get("phone"), "email": vault.get("email"),
            "contact_channel": consent.contact_channel, "contact_window": consent.contact_window,
            "nin": vault.get("nin"), "business_name": facts.get("business.name"),
            "business_registered": facts.get("business.registered"), "employer": facts.get("employment.employer"),
            "employment_type": facts.get("employment.type"), "farm_activity": facts.get("farm.activity"),
            "monthly_turnover": facts.get("business.monthly_turnover"),
            "monthly_income": facts.get("employment.monthly_net_income"),
            "annual_income": facts.get("farm.annual_income"), "monthly_repayments": facts.get("finance.monthly_repayments"),
        }
        customer_block["fields"] = {k: v for k, v in available.items() if k in decision.fields and v is not None}
        customer_block["verification"] = {"phone": True, "nin_provided": bool(vault.get("nin")),
                                          "level": cust.verification_level,
                                          "note": "Marketplace verification only — not institution KYC."}
        if "documents" in decision.fields:
            customer_block["documents"] = [
                {"id": str(d.id), "doc_type": d.doc_type, "filename": d.filename, "size": d.size}
                for d in db.execute(select(Document).where(Document.customer_id == opp.customer_id,
                                                           Document.pipeline_state.in_(["STORED", "CONFIRMED"]))).scalars()]
        audit(db, actor, "opportunity.viewed", "opportunity", opp.id, institution_id=opp.institution_id,
              after={"fields": sorted(customer_block["fields"].keys())})
        emit(db, "OpportunityViewed", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
             institution_id=opp.institution_id, data={"fields": len(customer_block["fields"])})
    return {**summary(db, opp, a), "customer": customer_block, "snapshot": opp.snapshot,
            "consent": {"status": consent.status if consent else None,
                        "categories": consent.data_categories if consent else [],
                        "version": consent.template_version if consent else None,
                        "granted_at": consent.granted_at.isoformat() if consent else None,
                        "withdrawn_at": consent.withdrawn_at.isoformat() if consent and consent.withdrawn_at else None},
            "activity": [{"kind": x.kind, "actor": x.actor, "note": x.note, "at": x.at.isoformat()} for x in
                         db.execute(select(Activity).where(Activity.opportunity_id == opp.id).order_by(Activity.at)).scalars()],
            "outcomes": [{"state": o.state, "reason": DECLINE_REASONS.get(o.reason_category or "", o.reason_category),
                          "note": o.reason_note, "approved_amount": float(o.approved_amount) if o.approved_amount else None,
                          "disbursed_amount": float(o.disbursed_amount) if o.disbursed_amount else None,
                          "disbursed_on": o.disbursed_on.isoformat() if o.disbursed_on else None,
                          "reported_at": o.reported_at.isoformat(), "label": "Reported by institution"}
                         for o in db.execute(select(Outcome).where(Outcome.opportunity_id == opp.id)
                                             .order_by(Outcome.reported_at)).scalars()],
            "decline_reasons": DECLINE_REASONS}


def summary(db: Session, opp: Opportunity, a: Assignment | None = None, product_names: dict | None = None,
            users: dict | None = None) -> dict:
    """Non-identifiable opportunity card (safe for any role with opportunity.read_meta)."""
    if a is None:
        a = db.get(Assignment, opp.id)
    snap = opp.snapshot or {}
    expl = (snap.get("match") or {}).get("explanation") or {}
    from weza.domains.identity.models import User
    owner = None
    if a and a.user_id:
        owner = (users or {}).get(a.user_id) or (db.get(User, a.user_id).full_name if db.get(User, a.user_id) else None)
    now = utcnow()
    due = a.first_contact_due_at if a and a.first_contact_at is None else None
    return {
        "id": str(opp.id), "reference": opp.reference, "state": opp.state, "freshness": opp.freshness,
        "priority": opp.priority, "amount": float(opp.amount), "currency": "UGX",
        "need": (snap.get("need") or {}).get("purpose") or opp.purpose_category,
        "purpose_category": opp.purpose_category, "customer_type": opp.customer_type, "sector": opp.sector,
        "district": opp.district, "match_score": round(opp.match_score), "quality_score": opp.quality_score,
        "product": (snap.get("product_version") or {}).get("name"),
        "why_matched": [x["text"] for x in expl.get("matched", [])][:5],
        "near_miss": [x["text"] for x in expl.get("near_miss", [])][:3],
        "components": (snap.get("match") or {}).get("components"),
        "owner": owner, "owner_id": str(a.user_id) if a and a.user_id else None,
        "team_id": str(a.team_id) if a and a.team_id else None,
        "assignment": a.assigned_by if a else None, "breach_state": a.breach_state if a else None,
        "first_contact_due_at": due.isoformat() if due else None,
        "minutes_to_target": int((due - now).total_seconds() // 60) if due else None,
        "age_hours": int((now - opp.qualified_at).total_seconds() // 3600),
        "qualified_at": opp.qualified_at.isoformat(), "routed_at": opp.routed_at.isoformat() if opp.routed_at else None,
        "integrity_hold": opp.integrity_hold, "is_demo": opp.is_demo,
        "next_action": _next_action(opp, a),
    }


def _next_action(opp: Opportunity, a: Assignment | None) -> str:
    if opp.integrity_hold:
        return "On hold — WEZA checks in progress"
    if a is None or a.user_id is None:
        return "Assign"
    return {"ROUTED": "Review & contact", "RECEIVED": "Contact customer", "ASSIGNED": "Contact customer",
            "CONTACTED": "Record progress", "PROCEEDING": "Report outcome", "SUBMITTED_TO_INSTITUTION": "Report outcome",
            "REPORTED_APPROVED": "Report disbursement"}.get(opp.state, "—")


# ------------------------------------------------------------------ worker sweeps (L6)


def service_target_sweep(db: Session) -> int:
    now = utcnow()
    n = 0
    rows = db.execute(select(Assignment, Opportunity).join(Opportunity, Opportunity.id == Assignment.opportunity_id)
                      .where(Assignment.first_contact_at.is_(None), Assignment.first_contact_due_at.is_not(None),
                             Opportunity.state.in_(["ROUTED", "RECEIVED", "ASSIGNED"]))).all()
    for a, opp in rows:
        st = db.get(ServiceTarget, opp.institution_id) or ServiceTarget(first_contact_within_minutes=1440,
                                                                        escalate_after_minutes=2880)
        total = (st.first_contact_within_minutes or 1440) * 60
        remaining = (a.first_contact_due_at - now).total_seconds()
        new = a.breach_state
        if remaining <= -((st.escalate_after_minutes or 2880) - (st.first_contact_within_minutes or 1440)) * 60:
            new = "ESCALATED"
        elif remaining <= 0:
            new = "BREACHED"
        elif remaining <= total * 0.25:
            new = "APPROACHING"
        if new != a.breach_state:
            a.breach_state = new
            if new in ("BREACHED", "ESCALATED"):
                a.breach_count += 1
            n += 1
            emit(db, {"APPROACHING": "ServiceTargetApproaching", "BREACHED": "ServiceTargetBreached",
                      "ESCALATED": "ServiceTargetEscalated"}[new], topic="opportunity", aggregate_type="opportunity",
                 aggregate_id=opp.id, institution_id=opp.institution_id,
                 data={"reference": opp.reference, "user_id": str(a.user_id) if a.user_id else None})
            if new == "ESCALATED":
                integrity.add_review(db, "SERVICE_TARGET", f"{opp.reference}: institution has not contacted the "
                                     "customer", "opportunity", opp.id, severity="MEDIUM", due_hours=24)
    return n


def freshness_sweep(db: Session) -> int:
    cfg, _ = get_config(db, "country:UG")
    fd = cfg.get("freshness_days", {"attention": 3, "stale": 7, "expired": 21})
    now = utcnow()
    n = 0
    for opp in db.execute(select(Opportunity).where(Opportunity.state.in_(OPEN_STATES - {"QUALIFIED"}))).scalars():
        idle = (now - opp.last_activity_at).days
        new = "EXPIRED" if idle >= fd["expired"] else "STALE" if idle >= fd["stale"] else \
            "ATTENTION_REQUIRED" if idle >= fd["attention"] else "FRESH"
        if new != opp.freshness:
            opp.freshness = new
            n += 1
            emit(db, "FreshnessChanged", topic="opportunity", aggregate_type="opportunity", aggregate_id=opp.id,
                 institution_id=opp.institution_id, data={"freshness": new, "reference": opp.reference})
            if new == "EXPIRED" and opp.state in ("ROUTED", "RECEIVED", "ASSIGNED", "CONTACTED"):
                opp.state, opp.closed_at = "EXPIRED", now
                db.add(Activity(opportunity_id=opp.id, kind="EXPIRED", actor="system",
                                note=f"No activity for {idle} days"))
    return n


def team_members(db: Session, institution_id) -> list[dict]:
    from weza.domains.identity.models import Membership, User
    rows = db.execute(select(User, Membership).join(Membership, Membership.user_id == User.id)
                      .where(Membership.institution_id == institution_id)).all()
    teams = {t.id: t.name for t in db.execute(select(Team).where(Team.institution_id == institution_id)).scalars()}
    return [{"id": str(u.id), "name": u.full_name, "email": u.email, "roles": m.roles, "status": u.status,
             "team_id": str(m.team_id) if m.team_id else None, "team": teams.get(m.team_id),
             "mfa_enrolled": u.mfa_enrolled} for u, m in rows]
