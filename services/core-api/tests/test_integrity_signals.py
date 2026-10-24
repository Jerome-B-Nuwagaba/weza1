"""Marketplace integrity (TSD §41): suspicious referral/partner activity and repeated disputes."""

import uuid

from sqlalchemy import select

from weza.domains.commercial.models import CommercialEvent, Dispute
from weza.domains.commercial.service import record_attribution
from weza.domains.customer import service as customer_svc
from weza.domains.integrity import service as integrity
from weza.domains.misc_models import ReviewItem
from weza.domains.need.models import FinancialNeed
from weza.platform.db import session_scope


def _arrive(db, attribution_id, n: int, flagged: int = 0):
    """n customers arriving through one referral code; the first `flagged` are already under integrity review."""
    made = []
    for i in range(n):
        phone = "+256771" + f"{uuid.uuid4().int % 10**6:06d}"
        cust, _ = customer_svc.get_or_create_by_phone(db, phone, attribution_id=attribution_id)
        if i < flagged:
            cust.integrity_state = "REVIEW"
        need = FinancialNeed(customer_id=cust.id, status="DRAFT", attribution_id=attribution_id)
        db.add(need)
        made.append((cust, need))
    db.flush()
    return made


def test_a_burst_through_one_referral_code_is_flagged_but_a_normal_trickle_is_not():
    with session_scope() as db:
        code = uuid.uuid4().hex[:8]
        attribution = record_attribution(db, source="partner", campaign="c1", partner=f"P{code}", referral=f"R{code}",
                                         channel="whatsapp", landing=None)
        quiet = _arrive(db, attribution.id, 5)
        _, signals = integrity.evaluate_customer(db, *quiet[-1])
        assert not [s for s in signals if s["kind"].startswith("REFERRAL")]
        busy = _arrive(db, attribution.id, integrity.REFERRAL_BURST_PER_DAY)  # now well over the daily limit
        _, signals = integrity.evaluate_customer(db, *busy[-1])
        kinds = {s["kind"]: s for s in signals}
        assert "REFERRAL_BURST" in kinds and kinds["REFERRAL_BURST"]["detail"]["partner"] == f"P{code}"
        assert "REFERRAL_ABUSE" not in kinds  # many arrivals alone are a burst, not abuse


def test_many_flagged_customers_from_one_code_is_referral_abuse():
    with session_scope() as db:
        code = uuid.uuid4().hex[:8]
        attribution = record_attribution(db, source="partner", campaign="c2", partner=f"P{code}", referral=f"R{code}",
                                         channel="whatsapp", landing=None)
        group = _arrive(db, attribution.id, 8, flagged=4)  # half of them already flagged
        state, signals = integrity.evaluate_customer(db, *group[-1])
        abuse = next(s for s in signals if s["kind"] == "REFERRAL_ABUSE")
        assert abuse["detail"]["flagged"] == 4 and abuse["weight"] == integrity.WEIGHTS["high"]
        assert state in ("REVIEW", "HIGH_RISK", "BLOCKED")  # a high-weight signal on its own reaches human review


def test_customers_with_no_partner_or_referral_code_are_not_judged_on_it():
    with session_scope() as db:
        direct = record_attribution(db, source="direct", campaign=None, partner=None, referral=None, channel="web",
                                    landing=None)
        group = _arrive(db, direct.id, integrity.REFERRAL_BURST_PER_DAY + 5)
        _, signals = integrity.evaluate_customer(db, *group[-1])
        assert not [s for s in signals if s["kind"].startswith("REFERRAL")]


def _billed_and_disputed(db, institution_id, billed: int, disputed: int):
    events = []
    for i in range(billed):
        ev = CommercialEvent(idempotency_key=f"test-dispute-pattern:{institution_id}:{i}", institution_id=institution_id,
                             kind="QUALIFIED_OPPORTUNITY", status="BILLABLE", billing_period="2026-10")
        db.add(ev)
        events.append(ev)
    db.flush()
    for ev in events[:disputed]:
        db.add(Dispute(commercial_event_id=ev.id, institution_id=institution_id, reason="NOT_QUALIFIED", state="OPEN"))
    db.flush()


def test_an_institution_disputing_most_of_its_bill_gets_a_human_review_and_nothing_else():
    with session_scope() as db:
        institution = uuid.uuid4()
        _billed_and_disputed(db, institution, billed=10, disputed=2)  # under the minimum: nothing
        assert integrity.check_dispute_pattern(db, institution) is None
    with session_scope() as db:
        institution = uuid.uuid4()
        _billed_and_disputed(db, institution, billed=10, disputed=3)  # 30% of the bill: below the share
        assert integrity.check_dispute_pattern(db, institution) is None
    with session_scope() as db:
        institution = uuid.uuid4()
        _billed_and_disputed(db, institution, billed=6, disputed=4)  # most of the bill
        item = integrity.check_dispute_pattern(db, institution)
        assert item is not None and item.kind == "REPEATED_DISPUTES" and item.severity == "MEDIUM"
        again = integrity.check_dispute_pattern(db, institution)  # the same month does not pile up reviews
        assert again.id == item.id
        assert db.execute(select(ReviewItem).where(ReviewItem.object_id == str(institution))).scalars().all() == [item]
        # billing is untouched: the events are still billable and the disputes still open
        assert {e.status for e in db.execute(select(CommercialEvent).where(
            CommercialEvent.institution_id == institution)).scalars()} == {"BILLABLE"}
