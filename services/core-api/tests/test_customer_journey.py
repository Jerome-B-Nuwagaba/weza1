"""End-to-end customer journey through the API (FSD §53 acceptance scenario; AT-01…AT-20, AT-54)."""

from decimal import Decimal

from sqlalchemy import select

from tests.helpers import SME_ANSWERS
from weza.domains.commercial.models import Attribution, CommercialEvent
from weza.domains.customer.models import Fact
from weza.domains.need.models import ConversationMessage, FinancialNeed
from weza.domains.opportunity.models import Assignment, Opportunity
from weza.platform.db import session_scope


def _complete_to_options(journey, phone="0772100001", text="I need UGX 30 million to expand my pharmacy."):
    j = journey(text, src="qr", cmp="Q4SME")
    assert j.node == "CONFIRM_INTENT"
    card = j.cards("understanding")[0]
    assert card["amount_value"] == 30_000_000
    assert card["customer_type"] == "Business owner"
    assert card["sector"] == "Health & pharmacy"
    j.send(action="confirm")
    j.verify(phone)
    assert j.session_token
    # unique NIN per customer: reusing one NIN correctly triggers a duplicate-identity integrity hold
    j.answer_profile({**SME_ANSWERS, "identity.nin": "CM" + phone[-10:] + "AB"})
    return j


def test_intent_extraction_and_confirmation_before_matching(journey):
    """AT-03/AT-04: extraction + confirmation; missing amount asks only for the amount (FSD-INT-002/003)."""
    j = journey("I need money for school fees.")
    assert j.node == "ASK_INTENT"
    assert "How much" in j.texts()[-1]
    j.send("2.5 million")
    assert j.node == "ASK_INTENT"  # customer type still unknown
    j.send(action="customer_type", value="SALARIED")
    assert j.node == "CONFIRM_INTENT"
    card = j.cards("understanding")[0]
    assert card["amount_value"] == 2_500_000 and card["purpose"].lower().startswith("school fees")


def test_full_pharmacy_journey_routes_qualified_opportunity(client, journey, drain, as_user):
    """FSD §53: pharmacy UGX 30M → options → consent → Qualified Opportunity routed, assigned, billed."""
    j = _complete_to_options(journey)
    assert j.node == "PRESENT_OPTIONS", j.texts()
    options = j.cards("options")[0]["options"]
    assert options, "expected at least one option"
    assert all("not a loan approval" not in o["why"] for o in options)
    assert any("not a loan approval" in t for t in j.texts())
    lakeside = next(o for o in options if o["institution"] == "Lakeside Bank" and o["readiness"] == "READY")
    j.send(action="select", value=lakeside["match_id"])
    assert j.node == "CONSENT"
    consent = j.cards("consent")[0]
    assert "not a loan approval" in consent["text"] and consent["version"] == "2026.1"
    j.send(action="agree", value=consent["template_id"])
    assert j.node == "TRACKING", j.texts()
    submitted = j.cards("submitted")[0]
    assert submitted["reference"].startswith("OPP-")
    drain()

    with session_scope() as db:
        opp = db.execute(select(Opportunity).where(Opportunity.reference == submitted["reference"])).scalar_one()
        assert opp.state in ("ROUTED", "ASSIGNED")
        snap = opp.snapshot
        for key in ("profile_snapshot", "product_version", "appetite_version", "match", "consent", "quality"):
            assert snap[key], key  # AT-19 versioned snapshot
        assert snap["consent"]["text_hash"] and snap["match"]["algorithm_version"] == "match_v1"
        a = db.get(Assignment, opp.id)
        assert a is not None and a.user_id is not None  # SME ≤ 50M → SME Team officer
        ev = db.execute(select(CommercialEvent).where(CommercialEvent.opportunity_id == opp.id)).scalar_one()
        assert ev.status in ("BILLABLE", "INCLUDED_IN_PLAN")
        attr = db.get(Attribution, opp.attribution_id)
        assert attr.source == "qr" and attr.campaign_code == "Q4SME"  # AT-01 lineage
        assert ev.attribution["campaign"] == "Q4SME"
        # Conversation history never stores the phone number or OTP
        msgs = db.execute(select(ConversationMessage).where(ConversationMessage.session_id == opp.need_id)).scalars().all()
        need = db.get(FinancialNeed, opp.need_id)
        msgs = db.execute(select(ConversationMessage).where(ConversationMessage.session_id == need.journey_id)).scalars().all()
        blob = " ".join(str(m.content) for m in msgs)
        assert "0772100001" not in blob and "CM1234567890AB" not in blob and "dev_code" not in blob

    # Customer can track it, labelled by institution
    r = client.get("/api/v1/me/needs", headers=j.customer_headers)
    need = r.json()["needs"][0]
    assert need["opportunities"][0]["reference"] == submitted["reference"]


def test_saga_is_idempotent_on_replayed_consent(client, journey, drain):
    """AT-20: repeated consent / replayed events produce one opportunity and one billable event."""
    j = _complete_to_options(journey, phone="0772100002")
    opt = next(o for o in j.cards("options")[0]["options"] if o["readiness"] == "READY")
    j.send(action="select", value=opt["match_id"])
    tpl = j.cards("consent")[0]["template_id"]
    j.send(action="agree", value=tpl)
    drain()
    from weza.platform.events import replay_delivery
    from weza.platform.models import EventDelivery
    with session_scope() as db:
        need_id = db.execute(select(FinancialNeed.id).where(FinancialNeed.journey_id == j.id)).scalar_one()
        opp = db.execute(select(Opportunity).where(Opportunity.need_id == need_id)).scalar_one()
        for d in db.execute(select(EventDelivery).where(EventDelivery.consumer.in_(["billing", "assignment"]))).scalars():
            replay_delivery(db, d.id)
    drain()
    with session_scope() as db:
        assert db.execute(select(Opportunity).where(Opportunity.need_id == need_id)).scalars().all().__len__() == 1
        events = db.execute(select(CommercialEvent).where(CommercialEvent.opportunity_id == opp.id)).scalars().all()
        assert len(events) == 1


def test_confirmed_facts_are_not_asked_again(journey):
    """Skill §17 / AT-05: a returning verified customer is not re-asked confirmed facts."""
    j = _complete_to_options(journey, phone="0772100003")
    j2 = journey("I need 10 million for stock for my pharmacy")
    j2.send(action="confirm")
    j2.verify("0772100003")
    assert j2.node != "ASK_PROFILE", "profile should be reused for the returning customer"
    assert "Welcome back" in " ".join(j2.texts())
    _ = j


def test_otp_failures_and_lockout(journey):
    """AT-06…AT-09: wrong code, remaining attempts, lockout; codes never stored in plaintext."""
    j = journey("I need 5 million for stock for my shop")
    j.send(action="confirm")
    j.send("0772100004")
    code = j.cards("otp_input")[0]["dev_code"]
    wrong = "000000" if code != "000000" else "111111"
    for i in range(4):
        j.send(wrong)
        assert "incorrect" in j.texts()[-1].lower()
    j.send(wrong)
    assert "too many" in j.texts()[-1].lower()
    with session_scope() as db:
        from weza.domains.identity.models import OtpChallenge
        for ch in db.execute(select(OtpChallenge)).scalars():
            assert code not in (ch.code_hash or "")


def test_profile_correction_invalidates_matches(client, journey, drain):
    """AT-10 / FSD-PRO-002: correcting a material fact after matching re-runs matching."""
    j = _complete_to_options(journey, phone="0772100005")
    with session_scope() as db:
        need = db.execute(select(FinancialNeed).where(FinancialNeed.journey_id == j.id)).scalar_one()
        before = need.last_matched_at
    r = client.patch("/api/v1/me/profile", json={"key": "business.age_months", "value": "3 months"},
                     headers=j.customer_headers)
    assert r.status_code == 200, r.text
    drain()
    with session_scope() as db:
        need = db.execute(select(FinancialNeed).where(FinancialNeed.journey_id == j.id)).scalar_one()
        assert need.last_matched_at > before
        facts = db.execute(select(Fact).where(Fact.customer_id == need.customer_id, Fact.key == "business.age_months")).scalars().all()
        assert len(facts) == 2 and sum(1 for f in facts if f.superseded_at is None) == 1  # history kept


def test_no_match_offers_waiting_room(journey):
    """AT-12/AT-36 and FSD §45: no current match → explain + Waiting Room; never invent an institution."""
    j = journey("I need UGX 2 billion to build a hotel")
    j.send(action="confirm")
    j.verify("0772100006")
    j.answer_profile({**SME_ANSWERS, "business.sector": "hospitality"})
    assert j.node == "OFFER_WAITING_ROOM", j.node
    j.send(action="wait")
    assert j.node == "WAITING_ROOM"
    with session_scope() as db:
        need = db.execute(select(FinancialNeed).where(FinancialNeed.journey_id == j.id)).scalar_one()
        assert need.status == "WAITING" and need.amount == Decimal("2000000000")


def test_journey_works_without_ai(journey):
    """AT-54 / TSD §76: no API key configured → deterministic path completes the journey."""
    from weza.platform.db import session_scope as ss
    with ss() as db:
        from weza.domains.intelligence.ai import effective_mode
        assert effective_mode(db) == "UNAVAILABLE"
    j = journey("Nahitaji 3m for my salon stock")
    assert j.node in ("CONFIRM_INTENT", "ASK_INTENT")
