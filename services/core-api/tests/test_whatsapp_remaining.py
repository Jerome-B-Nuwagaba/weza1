"""The remaining WhatsApp items from the 21 Oct review: tap-to-choose ranges for money and duration answers, the
off-topic guard, date of birth and expiry read from the National ID, and institution interest reaching the customer.
Same approach as test_whatsapp_less_typing.py: signed webhook -> inbox -> conversation graph, AI reader replaced by
fixed answers, no provider is ever called."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from tests.test_whatsapp_channel import (  # noqa: F401 — fixtures are picked up by name
    PNG,
    fake_phone,
    http,
    journeys_for,
    media_msg,
    out_messages,
    text_msg,
    wa_inbound,
    wa_live,
)
from tests.test_whatsapp_less_typing import (  # noqa: F401
    ID_READ,
    bot,
    button,
    facts,
    node,
    reader,
    state,
    to_id_request,
    vault,
)
from weza.domains.admin_config import ANSWER_BANDS, QUESTION_PATHS
from weza.domains.institution.models import Institution
from weza.domains.intelligence.ai import _plausible_date
from weza.domains.need.journey import _is_off_topic
from weza.domains.opportunity.models import Preview
from weza.platform.db import session_scope, utcnow
from weza.platform.models import GraphInstance

# ------------------------------------------------------------------ tap-to-choose ranges


def last_replies(phone) -> list[dict]:
    last = [m for m in out_messages(phone) if m.channel == "whatsapp"][-1]
    return (last.payload or {}).get("quick_replies") or []


def test_money_and_duration_questions_offer_ranges_to_tap_and_still_take_typing(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need 5 million for stock for my shop")
    button(client, phone, "confirm")
    text_msg(client, phone, "Grace Nakato")
    text_msg(client, phone, "skip")  # NIN
    if node(phone) == "REQUEST_BUSINESS_DOCS":
        text_msg(client, phone, "skip")
    typed = {"business.name": "Nakato Traders", "business.sector": "health_pharmacy", "business.district": "Kampala",
             "business.registered": "yes"}
    seen: dict[str, list[str]] = {}
    for _ in range(12):
        if node(phone) != "ASK_PROFILE":
            break
        key = state(phone)["pending_q"]["key"]
        if key in ANSWER_BANDS:
            seen[key] = [r["label"] for r in last_replies(phone)]
        if key == "business.age_months":
            button(client, phone, "answer:24")  # tapped: 24 MONTHS, not read as 24 years
        elif key == "business.monthly_turnover":
            button(client, phone, "answer:3000000")
        elif key == "finance.monthly_repayments":
            text_msg(client, phone, "UGX 500K - 1M")  # a typed range label works too
        elif key == "need.tenor_months":
            text_msg(client, phone, "2 years")  # an exact typed answer still goes through the normal parser
        else:
            text_msg(client, phone, typed[key])
    f = facts(state(phone)["customer_id"])
    assert f["business.age_months"].value["v"] == 24
    assert f["business.monthly_turnover"].value["v"] == 3_000_000
    assert f["finance.monthly_repayments"].value["v"] == 1_000_000  # the UPPER end: never understate existing debt
    assert f["need.tenor_months"].value["v"] == 24
    assert seen["business.monthly_turnover"][0] == "Under UGX 1M" and len(seen["business.monthly_turnover"]) == 6
    assert seen["need.tenor_months"][-1] == "Skip"  # an optional question gets a Skip option


def test_every_money_and_duration_question_has_ranges_with_ordered_distinct_values():
    money_months = {q["key"] for path in QUESTION_PATHS.values() for q in path if q["type"] in ("money", "months")}
    assert money_months == set(ANSWER_BANDS)  # a new money/duration question must get ranges, or a decision not to
    for key, bands in ANSWER_BANDS.items():
        values = [v for v, _ in bands]
        assert values == sorted(values) and len(set(values)) == len(values) and 4 <= len(bands) <= 10, key


# ------------------------------------------------------------------ off-topic guard


@pytest.mark.parametrize("text", ["what is the weather in Kampala today?", "tell me a joke please",
                                  "who won the football match yesterday", "are you a robot or a real person"])
def test_chit_chat_is_off_topic(text):
    assert _is_off_topic(text)


@pytest.mark.parametrize("text", ["I need UGX 5 million to buy stock", "how do I apply?", "what documents do I need",
                                  "hello", "Nakato Traders Ltd", "I run a barber in Gulu and want more chairs",
                                  "what interest rate do you charge?", "pharmacy", "Which banks are available?"])
def test_financing_talk_and_short_answers_are_never_turned_away(text):
    assert not _is_off_topic(text)


def test_off_topic_messages_are_redirected_then_the_conversation_pauses_and_resumes(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "what is the weather in Kampala today?")
    assert node(phone) == "GREET" and "I can only help with financing requests" in bot(phone)[-1]
    text_msg(client, phone, "tell me a joke please")
    assert node(phone) == "GREET" and "I can only help with financing requests" in bot(phone)[-1]
    text_msg(client, phone, "who won the football match yesterday?")
    assert node(phone) == "SAVE_EXIT" and "pause here" in bot(phone)[-2]  # then the standard "progress is saved"
    text_msg(client, phone, "I need 5 million for stock for my shop")  # a real request picks up from there
    assert node(phone) == "CONFIRM_INTENT"


def test_a_real_answer_clears_the_off_topic_count(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need to borrow money")
    assert node(phone) == "ASK_INTENT"
    text_msg(client, phone, "what is the weather today?")
    assert state(phone)["offtopic"] == 1
    text_msg(client, phone, "5 million")
    assert state(phone)["offtopic"] == 0


# ------------------------------------------------------------------ date of birth and expiry from the ID


def test_id_date_of_birth_and_expiry_are_kept_and_an_expired_card_is_flagged(client, wa_live, http, reader):
    phone = fake_phone()
    cid = to_id_request(client, phone)
    reader["id"].append({**ID_READ, "expiry_date": "2020-01-01"})
    http.media["ID9"] = (PNG, "image/png")
    media_msg(client, phone, "image", "ID9")
    button(client, phone, "confirm")
    assert vault(cid)["date_of_birth"] == "1990-04-02"  # encrypted identity vault: not a plain fact, not a lender field
    assert facts(cid)["identity.id_expiry"].value["v"] == "2020-01-01"
    assert any("expired on 2020-01-01" in b for b in bot(phone)[-3:])


@pytest.mark.parametrize("value,born,expected", [("1990-04-02", True, "1990-04-02"), ("2035-01-01", True, None),
                                                 ("1900-01-01", True, None), ("not a date", True, None),
                                                 (None, True, None), ("2020-01-01", False, "2020-01-01"),
                                                 ("2090-01-01", False, None)])
def test_only_plausible_dates_are_read_from_an_id(value, born, expected):
    assert _plausible_date(value, born=born) == expected


# ------------------------------------------------------------------ institution interest reaches the customer


def test_institution_interest_is_sent_once_with_a_show_options_button_that_works(client, as_user, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need 5 million for stock for my shop")
    button(client, phone, "confirm")
    need_id = state(phone)["need_id"]
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == "Lakeside Bank")).scalar_one()
        preview = Preview(need_id=uuid.UUID(need_id), match_id=uuid.uuid4(), institution_id=inst.id,
                          payload={"sector": "retail", "region": "Central", "customer_type": "SME"},
                          expires_at=utcnow() + timedelta(days=3))
        db.add(preview)
        db.flush()
        pid = str(preview.id)
        gi = db.get(GraphInstance, journeys_for(phone)[0][0])
        gi.current_node, gi.status, gi.waiting_for = "WAITING_ROOM", "WAITING", "CUSTOMER_REPLY"
    h = as_user("business@lakeside.demo")
    before = len(out_messages(phone))
    assert client.post(f"/api/v1/inst/previews/{pid}/interest", headers=h, json={"state": "INTERESTED"}).status_code == 200
    sent = out_messages(phone)[before:]
    assert len(sent) == 1 and "interested in your request" in sent[0].body
    assert "Lakeside" not in sent[0].body  # the institution is not named before the customer consents
    assert [q["action"] for q in sent[0].payload["quick_replies"]] == ["show_options"]
    client.post(f"/api/v1/inst/previews/{pid}/interest", headers=h, json={"state": "INTERESTED"})
    assert len(out_messages(phone)) == before + 1  # a repeat click does not message the customer again
    button(client, phone, "show_options")
    assert node(phone) != "WAITING_ROOM"  # the tap moved the conversation on
