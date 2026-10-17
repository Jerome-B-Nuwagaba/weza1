"""CRB identity verification in the customer journey (advisory), over the signed WhatsApp webhook and the web API.

The bureau is a local fake (tests/test_crb_client.FakeBureau); WhatsApp outbound stays in simulator mode. Nothing is
sent anywhere. Identity values are FAKE."""

import json
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import select

from tests.helpers import SME_ANSWERS, Journey
from tests.test_crb_client import BASE, NIN, FakeBureau, crb, enquiry, individual  # noqa: F401 — fixture by name
from tests.test_whatsapp_channel import (  # noqa: F401 — fixtures by name
    fake_phone,
    journeys_for,
    out_messages,
    rw,
    send,
    text_msg,
    verified_journey,
    wa_inbound,
)
from weza.config import get_settings
from weza.domains.customer import service as customer_svc
from weza.domains.customer.models import Customer
from weza.domains.misc_models import ReviewItem
from weza.domains.verification import gnugrid
from weza.domains.verification import service as idv
from weza.domains.verification.models import VerificationCheck
from weza.platform.db import session_scope, utcnow
from weza.platform.models import GraphInstance


def node(phone) -> str:
    return journeys_for(phone)[0][1]


def customer_of(phone) -> uuid.UUID:
    with session_scope() as db:
        return uuid.UUID(db.get(GraphInstance, journeys_for(phone)[0][0]).state["customer_id"])


def checks(cid) -> list[VerificationCheck]:
    with session_scope() as db:
        rows = db.execute(select(VerificationCheck).where(VerificationCheck.customer_id == cid)
                          .order_by(VerificationCheck.created_at)).scalars().all()
        db.expunge_all()
        return rows


def level(cid) -> str:
    with session_scope() as db:
        return db.get(Customer, cid).verification_level


def reviews(kind) -> list[ReviewItem]:
    with session_scope() as db:
        rows = db.execute(select(ReviewItem).where(ReviewItem.kind == kind)).scalars().all()
        db.expunge_all()
        return rows


def bot(phone) -> list[str]:
    return [m.body for m in out_messages(phone) if m.channel == "whatsapp"]


def to_dob_question(client, phone, name="John Okello", nin=NIN):
    verified_journey(client, phone)  # chat number verified by the channel → profile questions
    text_msg(client, phone, name)
    text_msg(client, phone, nin)


def consent_yes(client, phone):
    send(client, rw.build("button", phone=phone, button_id="idv_consent:yes"))


# ------------------------------------------------------------------ happy path


def test_whatsapp_customer_is_verified_after_consent(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone)
    assert node(phone) == "VERIFY_IDENTITY" and "date of birth" in bot(phone)[-1]
    assert crb.enquiries() == []  # nothing is sent before the date of birth and consent
    text_msg(client, phone, "31/03/1993")
    assert "credit reference bureau" in bot(phone)[-1] and crb.enquiries() == []  # consent asked first
    consent_yes(client, phone)
    (enq,) = crb.enquiries()
    assert enq["json"]["identifier"] == NIN and enq["json"]["client_consented"] == "Yes"
    cid = customer_of(phone)
    (chk,) = checks(cid)
    assert (chk.outcome, chk.status, chk.field_results) == ("VERIFIED", "COMPLETED",
                                                           {"name": "MATCH", "date_of_birth": "MATCH"})
    assert chk.consent_version == idv.CONSENT_VERSION and chk.consent_channel == "whatsapp"
    stored = json.dumps({c.name: str(getattr(chk, c.name)) for c in VerificationCheck.__table__.columns})
    assert NIN not in stored and "OKELLO" not in stored and "1993-03-31" not in stored  # outcome only
    assert level(cid) == "IDENTITY"
    assert any("match the record" in b for b in bot(phone))
    assert node(phone) == "ASK_PROFILE"  # the journey continues with the next question
    with session_scope() as db:
        assert db.get(GraphInstance, journeys_for(phone)[0][0]).state["pending_q"]["key"] == "business.name"
        facts = customer_svc.current_facts(db, cid)
        assert facts["identity.crb_verified"].verification_state == "VERIFIED"
        assert idv.status_for(db, cid)["identity_check"] == "VERIFIED"


def test_web_journey_applies_the_same_verification(client, crb):
    j = Journey(client, "I need 5 million for stock for my shop").send(action="confirm")
    j.verify("0772" + uuid.uuid4().hex[:6].translate(str.maketrans("abcdef", "123456")))  # web keeps the OTP
    j.answer_profile({**SME_ANSWERS, "identity.full_name": "John Okello"})
    assert j.node == "VERIFY_IDENTITY"
    j.send("31 March 1993").send(action="idv_consent", value="yes")
    assert len(crb.enquiries()) == 1 and any("match the record" in t for t in j.texts())


# ------------------------------------------------------------------ the customer decides


def test_declined_consent_means_no_enquiry(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "31/03/1993")
    send(client, rw.build("button", phone=phone, button_id="idv_consent:no"))
    assert crb.enquiries() == [] and node(phone) == "ASK_PROFILE"
    assert checks(customer_of(phone)) == [] and level(customer_of(phone)) == "PHONE"


def test_skipped_nin_means_no_date_of_birth_question_and_no_enquiry(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone, nin="skip")
    assert node(phone) == "ASK_PROFILE" and "date of birth" not in bot(phone)[-1]
    assert crb.enquiries() == []


def test_without_bureau_configuration_the_journey_is_unchanged(client, wa_inbound):
    phone = fake_phone()
    to_dob_question(client, phone)
    assert node(phone) == "ASK_PROFILE" and "date of birth" not in bot(phone)[-1]
    assert level(customer_of(phone)) == "PHONE"  # a typed NIN alone never means "identity verified"


# ------------------------------------------------------------------ discrepancies


def test_discrepancy_is_corrected_and_rechecked(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone, name="Peter Okello")
    text_msg(client, phone, "31/03/1993")
    consent_yes(client, phone)
    last = bot(phone)[-1]
    assert "name you gave doesn't match" in last and "fraud" not in last.lower()
    assert level(customer_of(phone)) == "PHONE"
    send(client, rw.build("button", phone=phone, button_id="idv_fix:name"))
    text_msg(client, phone, "John Bosco Okello")
    consent_yes(client, phone)  # a new enquiry needs a new yes
    assert len(crb.enquiries()) == 2
    assert [c.outcome for c in checks(customer_of(phone))] == ["DISCREPANCY", "VERIFIED"]
    assert level(customer_of(phone)) == "IDENTITY" and node(phone) == "ASK_PROFILE"


def test_customer_can_continue_without_correcting(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "01/01/1990")
    consent_yes(client, phone)
    assert "date of birth you gave doesn't match" in bot(phone)[-1]
    send(client, rw.build("button", phone=phone, button_id="idv_fix:continue"))
    assert node(phone) == "ASK_PROFILE" and len(crb.enquiries()) == 1 and level(customer_of(phone)) == "PHONE"


def test_unresolved_discrepancy_is_escalated_neutrally(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone, name="Peter Okello")
    text_msg(client, phone, "31/03/1993")
    consent_yes(client, phone)
    send(client, rw.build("button", phone=phone, button_id="idv_fix:name"))
    text_msg(client, phone, "Paul Okello")
    consent_yes(client, phone)
    assert node(phone) == "ASK_PROFILE" and "fraud" not in " ".join(bot(phone)).lower()
    review = next(r for r in reviews("IDENTITY_UNVERIFIED") if r.object_id == str(customer_of(phone)))
    assert "Not an indication of fraud" in review.title


def test_no_record_offers_to_check_the_id_number(client, wa_inbound, crb):
    crb.default = (200, enquiry(formal=[], informal=[]))
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "31/03/1993")
    consent_yes(client, phone)
    assert "couldn't find a record" in bot(phone)[-1]
    assert checks(customer_of(phone))[0].outcome == "NO_RECORD" and level(customer_of(phone)) == "PHONE"


# ------------------------------------------------------------------ failures never verify


def test_unavailable_bureau_lets_the_customer_continue_and_is_not_hammered(client, wa_inbound, crb):
    crb.default = (503, {"status": "error", "data": None, "message": "down", "code": 503})
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "31/03/1993")
    consent_yes(client, phone)
    assert any("isn't available right now" in b for b in bot(phone)[-3:]) and node(phone) == "ASK_PROFILE"
    cid = customer_of(phone)
    assert checks(cid)[0].outcome == "UNAVAILABLE" and level(cid) == "PHONE"
    with session_scope() as db:  # within the retry gap the same details are not resubmitted
        again = idv.run_check(db, cid, need_id=None, channel="whatsapp", consented_at=utcnow())
    assert again.reused and len(crb.enquiries()) == 1


def test_timeout_after_sending_is_uncertain_escalated_and_never_resubmitted(client, wa_inbound, crb):
    crb.responses = [httpx.ReadTimeout("no answer")]
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "31/03/1993")
    consent_yes(client, phone)
    cid = customer_of(phone)
    (chk,) = checks(cid)
    assert chk.outcome == "UNCERTAIN" and level(cid) == "PHONE"
    assert any(r.object_id == str(chk.id) for r in reviews("CRB_CHECK_UNRESOLVED"))
    with session_scope() as db:
        assert idv.needs_check(db, cid) is False


def test_bad_credentials_raise_an_ops_alert_and_never_verify(client, wa_inbound, crb):
    crb.token_response = (401, {"error": "invalid_client", "message": "Client authentication failed"})
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "31/03/1993")
    consent_yes(client, phone)
    assert checks(customer_of(phone))[0].outcome == "CONFIG_ERROR" and level(customer_of(phone)) == "PHONE"
    assert reviews("CRB_UNAVAILABLE") and SECRET_NOT_IN(reviews("CRB_UNAVAILABLE"))
    assert node(phone) == "ASK_PROFILE"


def SECRET_NOT_IN(items) -> bool:
    from tests.test_crb_client import SECRET
    return all(SECRET not in (r.title + json.dumps(r.detail)) for r in items)


# ------------------------------------------------------------------ idempotency and state


def test_duplicate_webhook_delivery_of_the_consent_sends_one_enquiry(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "31/03/1993")
    payload = rw.build("button", phone=phone, button_id="idv_consent:yes", message_id=f"wamid.FAKE_yes_{phone}")
    send(client, payload)
    send(client, payload)  # Meta retry
    assert len(crb.enquiries()) == 1


def test_same_details_are_never_enquired_twice(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "31/03/1993")
    consent_yes(client, phone)
    cid = customer_of(phone)
    with session_scope() as db:
        again = idv.run_check(db, cid, need_id=None, channel="whatsapp", consented_at=utcnow())
    assert again.reused and again.outcome == "VERIFIED" and len(crb.enquiries()) == 1


def test_crashed_request_is_treated_as_uncertain_not_resubmitted(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "31/03/1993")
    cid = customer_of(phone)
    with session_scope() as db:  # an attempt that was sent but whose process died before recording the answer
        key = idv._key(cid, idv._claims(db, cid))
        db.add(VerificationCheck(customer_id=cid, identification_type="ii_country_id", identifier_index="x",
                                 idempotency_key=key, status="REQUESTED", consent_version=idv.CONSENT_VERSION,
                                 consent_text_hash=idv.CONSENT_TEXT_HASH, consent_channel="whatsapp",
                                 consented_at=utcnow(), created_at=utcnow() - timedelta(hours=1)))
    with session_scope() as db:
        res = idv.run_check(db, cid, need_id=None, channel="whatsapp", consented_at=utcnow())
    assert res.outcome == "UNCERTAIN" and res.reused and crb.enquiries() == []


def test_new_identity_details_void_an_earlier_verification(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone)
    text_msg(client, phone, "31/03/1993")
    consent_yes(client, phone)
    cid = customer_of(phone)
    assert level(cid) == "IDENTITY"
    with session_scope() as db:
        customer_svc.upsert_fact(db, cid, "identity.nin", "CM9999999999ZZ", confirmed=True)
    with session_scope() as db:
        assert db.get(Customer, cid).verification_level == "PHONE"
        assert "identity.crb_verified" not in customer_svc.current_facts(db, cid)
        assert idv.status_for(db, cid)["identity_check"] == "NOT_CHECKED"


def test_institution_rule_field_reflects_only_a_verified_check(client, wa_inbound, crb):
    phone = fake_phone()
    to_dob_question(client, phone)
    cid = customer_of(phone)
    with session_scope() as db:
        assert customer_svc.rule_fields(db_need(db, phone), customer_svc.fact_values(db, cid))["identity_verified"] \
            is False
    text_msg(client, phone, "31/03/1993")
    consent_yes(client, phone)
    with session_scope() as db:
        assert customer_svc.rule_fields(db_need(db, phone), customer_svc.fact_values(db, cid))["identity_verified"] \
            is True


def db_need(db, phone):
    from weza.domains.need.models import FinancialNeed
    gi = db.get(GraphInstance, journeys_for(phone)[0][0])
    return db.get(FinancialNeed, uuid.UUID(gi.state["need_id"]))


def test_configuration_names_only(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "crb_base_url", "http://insecure.invalid")
    monkeypatch.setattr(s, "crb_client_id", "x")
    monkeypatch.setattr(s, "crb_client_secret", "FAKE_SECRET_NOT_TO_LOG")
    monkeypatch.setattr(s, "crb_enquiry_reason", "r")
    assert s.crb_missing == ["CRB_BASE_URL (must be https://)"] and not s.crb_ready
    assert "FAKE_SECRET_NOT_TO_LOG" not in json.dumps(s.channel_config_summary())


def test_parse_date_of_birth():
    from weza.domains.intelligence.parsing import parse_dob
    assert parse_dob("31/03/1993") == "1993-03-31" == parse_dob("31-3-1993") == parse_dob("1993-03-31")
    assert parse_dob("31 March 1993") == "1993-03-31" == parse_dob("March 31, 1993") == parse_dob("31st Mar 1993")
    assert parse_dob("31/02/1993") is None and parse_dob("01/01/2999") is None and parse_dob("yesterday") is None


_ = (BASE, FakeBureau, gnugrid, individual)
