"""WhatsApp with less typing (21 Oct 2026 review): the National ID photo gives the name and NIN, a business's
registration certificate and trading licence fill in what they can, and the number that receives the money is proven
by an SMS code typed back into the chat — the same code authorises the credit bureau check.

The AI reader is replaced by fixed answers here (tests never call a provider); everything else is the real pipeline:
signed webhook → inbox → media download → malware scan → encrypted storage → conversation graph."""

import re
import uuid

import pytest
from sqlalchemy import select

from scripts import replay_whatsapp_webhook as rw
from tests.test_whatsapp_channel import (  # noqa: F401 — fixtures are picked up by name
    PDF,
    PNG,
    fake_phone,
    http,
    journeys_for,
    media_msg,
    out_messages,
    send,
    stored_docs,
    text_msg,
    wa_inbound,
    wa_live,
)
from weza.config import get_settings
from weza.domains.customer.models import Customer, Fact
from weza.domains.identity.service import vault_read
from weza.domains.intelligence import ai
from weza.domains.need.models import ConversationMessage
from weza.platform.db import session_scope
from weza.platform.models import GraphInstance

NIN = "CM90123456ABCD"
ID_READ = {"full_name": "Grace Nakato", "nin": NIN, "date_of_birth": "1990-04-02"}


@pytest.fixture()
def reader(monkeypatch):
    """The AI document reader, answering from a queue of fixed results (None = unreadable)."""
    answers = {"id": [], "business": []}
    monkeypatch.setattr(ai, "can_read_documents", lambda db: True)
    monkeypatch.setattr(ai, "read_national_id", lambda db, mime, data, subject=None: answers["id"].pop(0))
    monkeypatch.setattr(ai, "read_business_document",
                        lambda db, mime, data, subject=None: answers["business"].pop(0))
    return answers


def button(client, phone, button_id):
    return send(client, rw.build("button", phone=phone, button_id=button_id))


def node(phone) -> str:
    return journeys_for(phone)[0][1]


def state(phone) -> dict:
    with session_scope() as db:
        return dict(db.get(GraphInstance, journeys_for(phone)[0][0]).state)


def bot(phone) -> list[str]:
    return [m.body for m in out_messages(phone) if m.channel == "whatsapp"]


def facts(customer_id) -> dict[str, Fact]:
    with session_scope() as db:
        rows = db.execute(select(Fact).where(Fact.customer_id == uuid.UUID(customer_id),
                                             Fact.superseded_at.is_(None))).scalars().all()
        db.expunge_all()
        return {f.key: f for f in rows}


def vault(customer_id) -> dict:
    with session_scope() as db:
        return vault_read(db, db.get(Customer, uuid.UUID(customer_id)).vault_token)


def to_id_request(client, phone) -> str:
    text_msg(client, phone, "I need 5 million for stock for my shop")
    button(client, phone, "confirm")
    assert node(phone) == "REQUEST_ID"
    assert "photo of the front of your National ID" in bot(phone)[-1]
    return state(phone)["customer_id"]


def test_id_photo_gives_name_and_nin_after_the_customer_confirms(client, wa_live, http, reader):
    phone = fake_phone()
    cid = to_id_request(client, phone)
    reader["id"].append(ID_READ)
    http.media["ID1"] = (PNG, "image/png")
    media_msg(client, phone, "image", "ID1")  # no caption: the conversation asked for the ID
    assert node(phone) == "CONFIRM_ID"
    (d,) = stored_docs(cid)
    assert d.doc_type == "national_id" and d.pipeline_state == "STORED"
    # The read-back carries the NIN: sent, but kept neither in the message log nor in the conversation history
    assert bot(phone)[-1] == "[identity details redacted]"
    with session_scope() as db:
        history = " ".join(str(m.content) for m in db.execute(select(ConversationMessage).where(
            ConversationMessage.session_id == journeys_for(phone)[0][0])).scalars())
    assert NIN not in history and "id_read_enc" in state(phone) and NIN not in str(state(phone))

    button(client, phone, "confirm")
    assert vault(cid)["full_name"] == "Grace Nakato" and vault(cid)["nin"] == NIN
    f = facts(cid)
    assert f["identity.full_name_captured"].source == "DOCUMENT"
    assert f["identity.full_name_captured"].source_ref == f"document:{d.id}"
    assert "identity.nin_captured" in f  # then checked against the registry like a typed NIN
    assert stored_docs(cid)[0].pipeline_state == "CONFIRMED"
    assert node(phone) == "REQUEST_BUSINESS_DOCS"  # a business owner: the licences come next, still no typing


def test_licences_fill_in_business_details_and_skip_those_questions(client, wa_live, http, reader):
    phone = fake_phone()
    cid = to_id_request(client, phone)
    reader["id"].append(ID_READ)
    http.media["ID2"] = (PNG, "image/png")
    media_msg(client, phone, "image", "ID2")
    button(client, phone, "confirm")
    assert node(phone) == "REQUEST_BUSINESS_DOCS"
    assert "business registration certificate and your trading licence" in bot(phone)[-1]

    reader["business"].append({"kind": "trading_licence", "business_name": "Nakato Traders",
                               "registration_number": "KCCA/TL/2026/001", "expiry_date": "2020-01-31"})
    http.media["TL1"] = (PDF, "application/pdf")
    media_msg(client, phone, "document", "TL1", filename="scan.pdf")
    assert node(phone) == "REQUEST_BUSINESS_DOCS"
    assert any("expired on 2020-01-31" in b for b in bot(phone)[-2:])
    assert "business registration certificate" in bot(phone)[-1]

    reader["business"].append({"kind": "business_registration", "business_name": "Nakato Traders Ltd",
                               "registration_number": "80020001234567", "expiry_date": None})
    http.media["BR1"] = (PDF, "application/pdf")
    media_msg(client, phone, "document", "BR1", filename="scan2.pdf")
    assert sorted(d.doc_type for d in stored_docs(cid)) == ["business_registration", "national_id", "trading_licence"]
    f = facts(cid)
    assert f["business.name"].value["v"] == "Nakato Traders" and f["business.name"].source == "AI_EXTRACTED"
    assert f["business.registered"].value["v"] is True and f["business.registered"].source == "DOCUMENT"
    assert f["business.registration_number"].value["v"] == "80020001234567"
    assert f["business.licence_expiry"].value["v"] == "2020-01-31"
    assert node(phone) == "ASK_PROFILE"
    key = state(phone)["pending_q"]["key"]
    assert key not in ("identity.full_name", "identity.nin", "business.name", "business.registered")


def test_unreadable_id_twice_falls_back_to_typing(client, wa_live, http, reader):
    phone = fake_phone()
    to_id_request(client, phone)
    reader["id"].extend([None, None])
    http.media["BAD1"] = (PNG, "image/png")
    media_msg(client, phone, "image", "BAD1")
    assert node(phone) == "REQUEST_ID" and "couldn't read that clearly" in bot(phone)[-1]
    http.media["BAD2"] = (PNG, "image/png")
    media_msg(client, phone, "image", "BAD2")
    assert node(phone) == "ASK_PROFILE" and state(phone)["pending_q"]["key"] == "identity.full_name"


def test_customer_can_choose_to_type_and_skip_the_licences(client, wa_inbound, reader):
    phone = fake_phone()
    to_id_request(client, phone)
    button(client, phone, "type_details")
    assert node(phone) == "ASK_PROFILE" and state(phone)["pending_q"]["key"] == "identity.full_name"
    text_msg(client, phone, "Grace Nakato")
    text_msg(client, phone, "skip")  # NIN
    assert node(phone) == "REQUEST_BUSINESS_DOCS"
    text_msg(client, phone, "skip")
    assert node(phone) == "ASK_PROFILE" and state(phone)["pending_q"]["key"] == "business.name"


def test_without_a_document_reader_the_customer_types_as_before(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need 5 million for stock for my shop")
    button(client, phone, "confirm")
    assert node(phone) == "ASK_PROFILE"  # no AI configured in tests: the typed path, unchanged


# ------------------------------------------------------------------ the number that receives the money

PROFILE = ["Grace Nakato", "skip", "skip", "Nakato Traders", "Kampala", "3 years", "12 million", "yes", "0",
           "12 months"]


def to_consent(client, phone, nin: str = "skip") -> None:
    text_msg(client, phone, "I need 5 million for stock for my shop")
    button(client, phone, "confirm")
    for answer in ["Grace Nakato", nin, *PROFILE[2:]]:
        if node(phone) not in ("ASK_PROFILE", "REQUEST_BUSINESS_DOCS"):
            break
        text_msg(client, phone, answer)
    assert node(phone) == "PRESENT_OPTIONS"
    text_msg(client, phone, "1")
    assert node(phone) == "CONSENT"
    agree = next(q for m in reversed(out_messages(phone)) for q in (m.payload or {}).get("quick_replies") or []
                 if q["action"] == "agree")
    button(client, phone, f"agree:{agree['value']}")


def last_code(phone_digits: str, digits: int) -> str:
    for body in reversed([m.body for m in out_messages(phone_digits)]):
        m = re.search(rf"\b(\d{{{digits}}})\b", body or "")
        if m:
            return m.group(1)
    raise AssertionError("no code sent")


def test_payout_number_is_proven_by_an_sms_code_typed_in_the_chat(client, wa_inbound):
    phone = fake_phone()
    to_consent(client, phone)
    assert node(phone) == "PAYOUT_NUMBER"
    assert "should receive the money" in bot(phone)[-1]
    payout = fake_phone()
    text_msg(client, phone, "0" + payout[-9:])  # another number, typed
    sms = [m for m in out_messages(payout) if m.channel == "sms"]
    assert sms and "verification code" in sms[-1].body  # the code goes to the payout number, by SMS
    text_msg(client, phone, "000000")
    assert node(phone) == "PAYOUT_NUMBER"  # wrong code: still waiting
    text_msg(client, phone, last_code(payout, 6))
    assert node(phone) == "TRACKING"
    cid = state(phone)["customer_id"]
    assert vault(cid)["payout_phone"].endswith(payout[-9:])
    with session_scope() as db:  # the number and the code are hidden in the conversation history
        history = " ".join(str(m.content) for m in db.execute(select(ConversationMessage).where(
            ConversationMessage.session_id == journeys_for(phone)[0][0])).scalars())
    assert payout[-9:] not in history


def test_one_code_verifies_the_number_and_authorises_the_bureau_check(client, wa_inbound, monkeypatch):
    from weza.domains.consent.models import CrbCheck
    from weza.integrations.gnugrid import MOCK_RECORD_PHONE
    monkeypatch.setattr(get_settings(), "crb_jit_enabled", True)
    phone = fake_phone()
    to_consent(client, phone, nin="CM90123456WXYZ")
    assert node(phone) == "CRB_CHECK"
    button(client, phone, "crb_consent:yes")
    assert node(phone) == "PAYOUT_NUMBER"
    text_msg(client, phone, MOCK_RECORD_PHONE)  # the number on the (offline) bureau record
    record = "256" + re.sub(r"\D", "", MOCK_RECORD_PHONE)[-9:]
    code = last_code(record, 10)
    text_msg(client, phone, code)
    assert node(phone) == "TRACKING"
    cid = uuid.UUID(state(phone)["customer_id"])
    with session_scope() as db:
        (check,) = db.execute(select(CrbCheck).where(CrbCheck.customer_id == cid)).scalars().all()
        assert check.status == "VERIFIED" and check.summary["phone_on_record"] is True


def test_phone_on_record_compares_the_last_nine_digits():
    from weza.integrations.gnugrid import phone_on_record
    details = {"Name": "X", "Contacts": [{"Mobile": "0772 123 456"}, {"Telephone": "+256 414 000000"}]}
    assert phone_on_record(details, "+256772123456") is True
    assert phone_on_record(details, "+256701000000") is False
    assert phone_on_record({"Contact": "<never stored>"}, "+256772123456") is None
    assert phone_on_record(details, None) is None
