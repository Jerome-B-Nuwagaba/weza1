"""Goal 4 — the customer credit-marketplace journey, end to end, to a Qualified Opportunity.

The WhatsApp channel is a live Meta integration owned elsewhere and is not available in this environment, so the
journey is driven through the web channel the browser client uses (`POST /api/v1/journeys`, then
`POST /api/v1/journeys/{id}/messages`). Nothing is faked: the journey graph, the matching engine, the consent
service, the opportunity saga, the routing and the audit trail are the production ones. The only development stub
is the one the web client already uses — the OTP code is displayed in the response in development mode.

Demo Bank is built through the real institution services (apply → verify → product → mandate → routing → activate),
so the journey ends at a named, ACTIVE lender rather than at a fixture.
"""

import uuid

import pytest
from sqlalchemy import select

from tests.helpers import SME_ANSWERS
from weza.domains.appetite import service as appetite_svc
from weza.domains.appetite.models import Appetite
from weza.domains.commercial.models import CommercialEvent
from weza.domains.consent.models import Consent, CrbCheck
from weza.domains.identity import service as identity
from weza.domains.identity.models import User
from weza.domains.matching.models import Match
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import Assignment, Opportunity
from weza.domains.trust.models import AuditEvent
from weza.platform.context import Actor
from weza.platform.db import session_scope
from weza.seed import seed_demo_bank

# The customer answers the minimum profile. No National ID: the bureau check is Just-In-Time and belongs to the
# lender-selection stage, so this journey never triggers one.
DEMO_ANSWERS = {**SME_ANSWERS, "identity.nin": "skip"}


@pytest.fixture(scope="module")
def demo_bank():
    """Demo Bank — one ACTIVE product and one ACTIVE mandate, routed to its own SME desk."""
    with session_scope() as db:
        state = seed_demo_bank(db)
        return {"id": str(state["inst"].id), "name": state["inst"].display_name}


def _need_for(journey):
    with session_scope() as db:
        return db.execute(select(FinancialNeed).where(
            FinancialNeed.journey_id == uuid.UUID(journey.id))).scalar_one()


def _to_options(journey, phone: str, text: str, answers: dict | None = None):
    """A stated need → confirmed intent → verified phone → minimum profile → the options weza can offer."""
    j = journey(text)
    assert j.node == "CONFIRM_INTENT", j.texts()
    j.send(action="confirm")
    j.verify(phone)
    j.answer_profile(answers or DEMO_ANSWERS)
    return j


def _demo_option(journey):
    options = journey.cards("options")[0]["options"]
    return next(o for o in options if o["institution"] == "Demo Bank")


def test_happy_path_customer_reaches_a_qualified_opportunity_at_demo_bank(journey, drain, demo_bank):
    """Stated need → OTP-verified phone → minimum profile → explainable scores → consent → Qualified Opportunity
    routed to Demo Bank. No bureau call: the credit check is the lender's, at their stage."""
    j = _to_options(journey, "0772400001", "I need UGX 30 million to expand my pharmacy")
    assert j.node == "PRESENT_OPTIONS", j.node

    options = j.cards("options")[0]["options"]
    assert any(o["institution"] == "Demo Bank" for o in options)
    demo = _demo_option(j)
    assert demo["readiness"] == "READY"
    assert demo["product"] == "SME Working Capital"
    # The score is explainable — components, not a black box — and it is not a promise of approval.
    assert demo["score"] > 0
    assert set(demo["components"]) == {"product_fit", "appetite_fit", "preference_fit", "readiness", "capacity_fit"}
    assert any("not a loan approval" in t for t in j.texts())

    j.send(action="select", value=demo["match_id"])
    assert j.node == "CONSENT", j.node
    consent_card = j.cards("consent")[0]
    assert consent_card["institution"] == "Demo Bank"  # the consent is for this institution
    assert "not a loan approval" in consent_card["text"]

    j.send(action="agree", value=consent_card["template_id"])
    assert j.node == "TRACKING", j.texts()
    submitted = j.cards("submitted")[0]
    assert submitted["institution"] == "Demo Bank"
    assert submitted["reference"].startswith("OPP-")
    drain()

    need = _need_for(j)
    with session_scope() as db:
        opp = db.execute(select(Opportunity).where(Opportunity.need_id == need.id)).scalar_one()
        assert opp.state in ("ROUTED", "ASSIGNED")
        assert str(opp.institution_id) == demo_bank["id"]
        assert opp.match_score > 0
        snap = opp.snapshot
        # the versioned product and mandate the customer was actually shown
        assert snap["product_version"]["name"] == "SME Working Capital"
        assert snap["appetite_version"]["id"]
        assert snap["match"]["algorithm_version"] and snap["quality"]["score"] > 0
        # the consent behind the share, with its version and hash
        assert snap["consent"]["version"] and snap["consent"]["text_hash"]
        consent = db.get(Consent, opp.consent_id)
        assert consent.status == "GRANTED" and str(consent.institution_id) == demo_bank["id"]
        # routed to a Demo Bank officer
        assignment = db.get(Assignment, opp.id)
        assert assignment is not None and assignment.user_id is not None
        assert db.get(User, assignment.user_id).email.endswith("@demobank.demo")
        # no bureau call was made for this journey
        assert db.execute(select(CrbCheck).where(CrbCheck.customer_id == need.customer_id)).scalars().all() == []
        # audit trail: the consent and the routing
        opp_actions = {row.action for row in db.execute(select(AuditEvent).where(
            AuditEvent.object_type == "opportunity", AuditEvent.object_id == str(opp.id))).scalars()}
        assert "opportunity.routed" in opp_actions
        consent_actions = {row.action for row in db.execute(select(AuditEvent).where(
            AuditEvent.object_type == "consent", AuditEvent.object_id == str(consent.id))).scalars()}
        assert "consent.granted" in consent_actions


def test_no_match_customer_is_offered_the_waiting_room_and_no_opportunity(journey, drain, demo_bank):
    """A need no active product and mandate can serve → an explanation and the Waiting Room, never a made-up
    institution, and never an opportunity."""
    j = journey("I need UGX 2 billion to build a hotel")
    j.send(action="confirm")
    j.verify("0772400002")
    j.answer_profile({**DEMO_ANSWERS, "business.name": "Sunrise Hotel Ltd", "business.sector": "hospitality",
                      "business.monthly_turnover": "40 million"})
    assert j.node == "OFFER_WAITING_ROOM", j.node
    assert j.cards("options") == []
    need = _need_for(j)
    with session_scope() as db:
        assert db.execute(select(Opportunity).where(Opportunity.need_id == need.id)).scalars().all() == []
        assert db.execute(select(Consent).where(Consent.need_id == need.id)).scalars().all() == []


def test_without_consent_nothing_is_shared_or_routed(journey, drain, demo_bank, client, as_user):
    """The customer can stop at the consent step: no consent, no opportunity, and Demo Bank's workspace is
    unchanged — nothing identifiable was routed."""
    j = _to_options(journey, "0772400003", "I need UGX 25 million to buy stock for my pharmacy")
    demo = _demo_option(j)
    headers = as_user("admin@demobank.demo")
    before = client.get("/api/v1/inst/opportunities", headers=headers).json()["total"]
    j.send(action="select", value=demo["match_id"])
    assert j.node == "CONSENT", j.node
    j.send(action="decline")
    assert j.node == "PRESENT_OPTIONS", j.node
    assert any("nothing has been shared" in t for t in j.texts())

    need = _need_for(j)
    with session_scope() as db:
        assert db.execute(select(Opportunity).where(Opportunity.need_id == need.id)).scalars().all() == []
        assert db.execute(select(Consent).where(Consent.need_id == need.id)).scalars().all() == []
        # no consent was granted, so no consent was ever audited for this match
        assert db.execute(select(AuditEvent).where(
            AuditEvent.action == "consent.granted", AuditEvent.institution_id == uuid.UUID(demo_bank["id"]),
            AuditEvent.object_type == "consent", AuditEvent.object_id.in_(
                [str(c.id) for c in db.execute(select(Consent).where(
                    Consent.need_id == need.id)).scalars()]))).scalars().all() == []
    # the lender's workspace did not grow: this customer never arrived
    after = client.get("/api/v1/inst/opportunities", headers=headers).json()["total"]
    assert after == before


def test_a_replayed_consent_never_creates_a_second_opportunity(journey, drain, demo_bank):
    """Duplicate protection: a double-tapped "I agree" and a replayed saga produce one opportunity, one
    assignment and one billable event."""
    j = _to_options(journey, "0772400004", "I need UGX 18 million for stock in my pharmacy")
    demo = _demo_option(j)
    j.send(action="select", value=demo["match_id"])
    template_id = j.cards("consent")[0]["template_id"]
    j.send(action="agree", value=template_id)
    drain()
    j.send(action="agree", value=template_id)  # the customer taps "I agree" twice
    drain()

    need = _need_for(j)
    with session_scope() as db:
        opps = db.execute(select(Opportunity).where(Opportunity.need_id == need.id)).scalars().all()
        assert len(opps) == 1
        opp = opps[0]
        # replaying the saga (a redelivered event) returns the same opportunity
        match = db.get(Match, uuid.UUID(demo["match_id"]))
        consent = db.execute(select(Consent).where(Consent.match_id == match.id)).scalar_one()
        again = opp_svc.qualify(db, Actor(kind="CUSTOMER", id=need.customer_id, display="customer"), need, match,
                                consent)
        assert again.id == opp.id
        assert len(db.execute(select(Opportunity).where(Opportunity.need_id == need.id)).scalars().all()) == 1
        assert len(db.execute(select(Assignment).where(Assignment.opportunity_id == opp.id)).scalars().all()) == 1
        # one billable event, not two
        assert len(db.execute(select(CommercialEvent).where(
            CommercialEvent.opportunity_id == opp.id)).scalars().all()) == 1


def test_an_inactive_mandate_never_produces_an_opportunity(journey, drain, demo_bank):
    """A mandate paused between selection and consent must not yield an opportunity: the option is stale."""
    j = _to_options(journey, "0772400005", "I need UGX 22 million to expand my pharmacy")
    demo = _demo_option(j)
    j.send(action="select", value=demo["match_id"])
    assert j.node == "CONSENT", j.node
    # The mandate behind the option the customer chose (Demo Bank may carry other mandates from other tests).
    with session_scope() as db:
        appetite_id = db.get(Match, uuid.UUID(demo["match_id"])).appetite_id
        appetite = db.get(Appetite, appetite_id)
        admin = db.execute(select(User).where(User.email == "admin@demobank.demo")).scalar_one()
        actor = identity.actor_for_user(db, admin, mfa=True)
        appetite_svc.set_lifecycle(db, actor, appetite, "PAUSED", "Paused for the demo")
    try:
        j.send(action="agree", value=j.cards("consent")[0]["template_id"])
        assert any("changed just now" in t for t in j.texts())
        need = _need_for(j)
        with session_scope() as db:
            assert db.execute(select(Opportunity).where(Opportunity.need_id == need.id)).scalars().all() == []
    finally:
        with session_scope() as db:
            appetite = db.get(Appetite, appetite_id)
            admin = db.execute(select(User).where(User.email == "admin@demobank.demo")).scalar_one()
            actor = identity.actor_for_user(db, admin, mfa=True)
            appetite_svc.set_lifecycle(db, actor, appetite, "ACTIVE", "Resumed after the demo")
