"""Marketplace Integrity Engine (FSD §38, TSD §41; blueprint L4). Integrity protects the marketplace and is
never presented as creditworthiness."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.customer.models import Customer
from weza.domains.identity.models import VaultRecord
from weza.domains.misc_models import IntegrityCase, IntegritySignal, ReviewItem
from weza.domains.need.models import ConversationMessage, FinancialNeed
from weza.platform.db import utcnow
from weza.platform.events import emit

RULE_VERSION = "integrity_v1"
WEIGHTS = {"high": 60, "medium": 30}
# Suspicious referral / partner activity (TSD §41). Codes are marketing identifiers, never personal data.
REFERRAL_BURST_PER_DAY = 20  # customers arriving through one partner+referral code in 24 hours
REFERRAL_FLAGGED_MIN, REFERRAL_FLAGGED_SHARE = 3, 0.4  # flagged customers from the same code, and their share
# Repeated disputes (TSD §41): an institution disputing most of what it is billed is a pattern worth a human's look.
DISPUTE_MIN, DISPUTE_SHARE, DISPUTE_DAYS = 3, 0.5, 90


def _referral_signals(db: Session, customer: Customer, now) -> list[dict]:
    from weza.domains.commercial.models import Attribution
    a = db.get(Attribution, customer.attribution_id) if customer.attribution_id else None
    if a is None or not (a.partner_code or a.referral_code):
        return []
    same_code = select(Attribution.id).where(Attribution.partner_code.is_not_distinct_from(a.partner_code),
                                             Attribution.referral_code.is_not_distinct_from(a.referral_code))
    states = db.execute(select(Customer.integrity_state).where(
        Customer.attribution_id.in_(same_code), Customer.created_at >= now - timedelta(days=1))).scalars().all()
    detail = {"partner": a.partner_code, "referral": a.referral_code, "customers_24h": len(states)}
    out = []
    if len(states) > REFERRAL_BURST_PER_DAY:
        out.append({"kind": "REFERRAL_BURST", "weight": WEIGHTS["medium"], "detail": detail})
    flagged = sum(1 for s in states if s != "NORMAL")
    if flagged >= REFERRAL_FLAGGED_MIN and flagged / len(states) >= REFERRAL_FLAGGED_SHARE:
        out.append({"kind": "REFERRAL_ABUSE", "weight": WEIGHTS["high"], "detail": {**detail, "flagged": flagged}})
    return out


def check_dispute_pattern(db: Session, institution_id: uuid.UUID) -> ReviewItem | None:
    """After a billing dispute: if this institution is disputing most of what it is billed, ask a person to look.
    Disputes are legitimate, so this only raises a review item; it never changes billing or blocks anything."""
    from weza.domains.commercial.models import CommercialEvent, Dispute
    since = utcnow() - timedelta(days=DISPUTE_DAYS)
    disputes = db.execute(select(func.count()).select_from(Dispute).where(
        Dispute.institution_id == institution_id, Dispute.created_at >= since)).scalar_one()
    billed = db.execute(select(func.count()).select_from(CommercialEvent).where(
        CommercialEvent.institution_id == institution_id, CommercialEvent.kind == "QUALIFIED_OPPORTUNITY",
        CommercialEvent.status != "NOT_BILLABLE", CommercialEvent.created_at >= since)).scalar_one()
    if disputes < DISPUTE_MIN or not billed or disputes / billed < DISPUTE_SHARE:
        return None
    db.add(IntegritySignal(kind="REPEATED_DISPUTES", subject_type="institution", subject_id=str(institution_id),
                           weight=WEIGHTS["medium"], rule_version=RULE_VERSION,
                           detail={"disputes": disputes, "billed": billed, "days": DISPUTE_DAYS}))
    return add_review(db, "REPEATED_DISPUTES", f"Institution disputed {disputes} of {billed} billed opportunities in "
                      f"{DISPUTE_DAYS} days", "institution", institution_id, severity="MEDIUM",
                      detail={"disputes": disputes, "billed": billed}, due_hours=120,
                      dedupe_key=f"REPEATED_DISPUTES:{institution_id}:{utcnow():%Y-%m}")


def evaluate_customer(db: Session, customer: Customer, need: FinancialNeed) -> tuple[str, list[dict]]:
    """Return (risk_state, signals). NORMAL < 60 ≤ REVIEW < 100 ≤ HIGH_RISK < 150 ≤ BLOCKED."""
    now = utcnow()
    signals: list[dict] = []
    n_needs = db.execute(select(func.count()).select_from(FinancialNeed).where(
        FinancialNeed.customer_id == customer.id, FinancialNeed.created_at >= now - timedelta(days=7))).scalar_one()
    if n_needs > 3:
        signals.append({"kind": "VELOCITY", "weight": WEIGHTS["medium"], "detail": {"needs_7d": n_needs}})
    rec = db.get(VaultRecord, customer.vault_token)
    if rec and rec.nin_index:
        shared = db.execute(select(func.count()).select_from(VaultRecord).where(
            VaultRecord.nin_index == rec.nin_index, VaultRecord.id != rec.id)).scalar_one()
        if shared:
            signals.append({"kind": "DUPLICATE_IDENTITY", "weight": WEIGHTS["high"], "detail": {"other_records": shared}})
    if customer.device_hash:
        devices = db.execute(select(func.count()).select_from(Customer).where(
            Customer.device_hash == customer.device_hash, Customer.created_at >= now - timedelta(days=7))).scalar_one()
        if devices > 3:
            signals.append({"kind": "DEVICE_REUSE", "weight": WEIGHTS["medium"], "detail": {"customers": devices}})
    signals += _referral_signals(db, customer, now)
    from weza.domains.verification.service import latest as latest_identity_check
    check = latest_identity_check(db, customer.id)
    if check is not None and check.status in ("NOT_FOUND", "MISMATCH"):
        signals.append({"kind": f"IDENTITY_{check.status}", "weight": WEIGHTS["high"],
                        "detail": {"provider": check.provider, "check": str(check.id)}})
    first_msg = db.execute(select(ConversationMessage.content).where(
        ConversationMessage.customer_id == customer.id, ConversationMessage.direction == "IN")
        .order_by(ConversationMessage.received_at).limit(1)).scalar_one_or_none()
    if first_msg and first_msg.get("text") and len(first_msg["text"]) > 25:
        same = db.execute(select(func.count(func.distinct(ConversationMessage.customer_id))).where(
            ConversationMessage.direction == "IN", ConversationMessage.content["text"].astext == first_msg["text"],
            ConversationMessage.received_at >= now - timedelta(days=1))).scalar_one()
        if same > 5:
            signals.append({"kind": "SYNTHETIC_PATTERN", "weight": WEIGHTS["medium"], "detail": {"identical": same}})
    score = sum(s["weight"] for s in signals)
    state = "BLOCKED" if score >= 150 else "HIGH_RISK" if score >= 100 else "REVIEW" if score >= 60 else "NORMAL"
    for s in signals:
        db.add(IntegritySignal(kind=s["kind"], subject_type="customer", subject_id=str(customer.id),
                               weight=s["weight"], rule_version=RULE_VERSION, detail=s["detail"]))
    if state != customer.integrity_state and state != "NORMAL":
        customer.integrity_state = state
        emit(db, "IntegritySignalRaised", topic="integrity", aggregate_type="customer", aggregate_id=customer.id,
             data={"state": state, "score": score})
    return state, signals


def open_case(db: Session, subject_type: str, subject_id, score_state: str, signals: list[dict], context: dict) -> IntegrityCase:
    existing = db.execute(select(IntegrityCase).where(IntegrityCase.subject_type == subject_type,
                                                      IntegrityCase.subject_id == str(subject_id),
                                                      IntegrityCase.state == "OPEN")).scalar_one_or_none()
    if existing:
        return existing
    case = IntegrityCase(subject_type=subject_type, subject_id=str(subject_id),
                         score=sum(s["weight"] for s in signals), risk_state=score_state, signals=signals,
                         context=context)
    db.add(case)
    db.flush()
    add_review(db, "INTEGRITY", f"Integrity review: {score_state.replace('_', ' ').lower()} {subject_type}",
               "integrity_case", case.id, severity="HIGH" if score_state != "REVIEW" else "MEDIUM",
               detail={"signals": [s["kind"] for s in signals], **context}, due_hours=48)
    emit(db, "IntegrityCaseOpened", topic="integrity", aggregate_type="integrity_case", aggregate_id=case.id,
         data={"risk_state": score_state})
    return case


def add_review(db: Session, kind: str, title: str, object_type: str, object_id, *, severity: str = "MEDIUM",
               detail: dict | None = None, due_hours: int | None = None, dedupe_key: str | None = None) -> ReviewItem:
    key = dedupe_key or f"{kind}:{object_type}:{object_id}"
    existing = db.execute(select(ReviewItem).where(ReviewItem.dedupe_key == key)).scalar_one_or_none()
    if existing:
        if existing.status != "OPEN":
            existing.status = "OPEN"
        return existing
    item = ReviewItem(kind=kind, title=title, object_type=object_type, object_id=str(object_id), severity=severity,
                      detail=detail or {}, dedupe_key=key,
                      due_at=(utcnow() + timedelta(hours=due_hours)) if due_hours else None)
    db.add(item)
    db.flush()
    return item


def subject_uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)
