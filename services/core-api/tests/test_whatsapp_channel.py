"""WhatsApp channel: webhook, signature, inbound handling, outbound shape, placeholder handling.

All credentials here are FAKE and local. No test may reach Meta or an SMS provider: `httpx.post` is replaced by a
recorder (any un-mocked call fails the test). Phone numbers are obviously fake Ugandan-format numbers.
Tests marked xfail(strict) describe behaviour that later hardening steps (b/c/d) will deliver; when the
behaviour lands the strict xfail flips to a failure, forcing the marker to be removed.
"""

import hmac
import itertools
import json
import logging

import httpx
import pytest
from sqlalchemy import func, select

from scripts import replay_whatsapp_webhook as rw
from weza.config import get_settings, is_configured
from weza.domains.intelligence.parsing import parse_phone
from weza.domains.misc_models import ChannelMessage, WhatsappInbox
from weza.domains.need.models import ConversationMessage
from weza.domains.notification import service as notify
from weza.platform import crypto
from weza.platform.controls import rate_limit
from weza.platform.db import session_scope
from weza.platform.events import drain
from weza.platform.logging import JsonFormatter
from weza.platform.models import GraphInstance

URL = "/api/v1/channels/whatsapp/webhook"
_seq = itertools.count(1)
_wamid = itertools.count(1)


def fake_phone() -> str:
    """Digits only, unique per call, e.g. 256772000001."""
    return f"2567720{next(_seq):05d}"


def idx_of(digits: str) -> str:
    return crypto.blind_index("phone", parse_phone("+" + digits))


# ------------------------------------------------------------------ fixtures


class Http:
    """Recorder replacing httpx.post for outbound WhatsApp sends."""

    def __init__(self):
        self.calls: list[dict] = []
        self.behaviour = "unexpected"  # unexpected | ok | http500 | timeout
        self.n = 0

    def __call__(self, url, json=None, headers=None, timeout=None, **kw):
        if self.behaviour == "unexpected":
            raise AssertionError("real network call attempted")
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.behaviour == "timeout":
            raise httpx.ConnectTimeout("fake timeout")
        code = 500 if self.behaviour == "http500" else 200
        self.n += 1
        return httpx.Response(code, json={"messages": [{"id": f"wamid.FAKE_OUT_{next(_wamid)}"}]},
                              request=httpx.Request("POST", url))


@pytest.fixture(autouse=True)
def http(monkeypatch):
    rec = Http()
    monkeypatch.setattr(httpx, "post", rec)
    return rec


@pytest.fixture()
def wa_inbound(monkeypatch):
    """Fake webhook secret + verify token (inbound only; outbound stays in simulator mode)."""
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_app_secret", rw.FAKE_APP_SECRET)
    monkeypatch.setattr(s, "whatsapp_verify_token", rw.FAKE_VERIFY_TOKEN)
    return s


@pytest.fixture()
def wa_live(wa_inbound, monkeypatch, http):
    """Additionally treat outbound as configured (fake token/phone id) with the HTTP client mocked as OK."""
    monkeypatch.setattr(wa_inbound, "whatsapp_token", "FAKE_token_not_real")
    monkeypatch.setattr(wa_inbound, "whatsapp_phone_number_id", "000000000000000")
    http.behaviour = "ok"
    return wa_inbound


def post_raw(client, raw: bytes, *, signature="auto"):
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        headers["X-Hub-Signature-256"] = rw.sign(raw)
    elif signature:
        headers["X-Hub-Signature-256"] = signature
    return client.post(URL, content=raw, headers=headers)


def send(client, payload: dict, *, signature="auto", process=True):
    """POST a signed webhook; by default also run the worker (drain) so queued inbound messages are processed."""
    r = post_raw(client, json.dumps(payload).encode(), signature=signature)
    if process:
        drain()
    return r


def text_msg(client, phone, text, mid=None, process=True):
    return send(client, rw.build("text", phone=phone, text=text, message_id=mid), process=process)


def inbox_rows(digits: str) -> list[WhatsappInbox]:
    with session_scope() as db:
        rows = db.execute(select(WhatsappInbox).where(WhatsappInbox.phone_index == idx_of(digits))
                          .order_by(WhatsappInbox.received_at, WhatsappInbox.id)).scalars().all()
        db.expunge_all()
        return rows


def journeys_for(digits: str) -> list[tuple[str, str]]:
    with session_scope() as db:
        rows = db.execute(select(GraphInstance).where(
            GraphInstance.graph_type == "customer_journey",
            GraphInstance.state["wa_index"].astext == idx_of(digits))).scalars().all()
        return [(str(g.id), g.current_node) for g in rows]


def in_messages(journey_id: str) -> list[str]:
    with session_scope() as db:
        return [m.message_id for m in db.execute(select(ConversationMessage).where(
            ConversationMessage.session_id == journey_id, ConversationMessage.direction == "IN")).scalars()]


def out_messages(digits: str) -> list[ChannelMessage]:
    with session_scope() as db:
        rows = db.execute(select(ChannelMessage).where(ChannelMessage.to_index == idx_of(digits))
                          .order_by(ChannelMessage.created_at)).scalars().all()
        db.expunge_all()
        return rows


# ------------------------------------------------------------------ config / placeholders


@pytest.mark.parametrize("value,expected", [(None, False), ("", False), ("   ", False), ("REPLACE_ME", False),
                                            ("replace_me", False), ("FAKE_token", True)])
def test_is_configured(value, expected):
    assert is_configured(value) is expected


def test_placeholder_secrets_mean_not_configured(client, monkeypatch):
    s = get_settings()
    for name in ("whatsapp_app_secret", "whatsapp_verify_token", "whatsapp_token", "whatsapp_phone_number_id"):
        monkeypatch.setattr(s, name, "REPLACE_ME")
    assert not (s.whatsapp_webhook_ready or s.whatsapp_verify_ready or s.whatsapp_send_ready)
    # A request signed with the literal placeholder must NOT be accepted.
    raw = json.dumps(rw.build("text", phone=fake_phone())).encode()
    r = client.post(URL, content=raw, headers={"X-Hub-Signature-256": rw.sign(raw, "REPLACE_ME")})
    assert r.status_code == 403
    r = client.get(URL, params={"hub.mode": "subscribe", "hub.verify_token": "REPLACE_ME", "hub.challenge": "1"})
    assert r.status_code == 403
    assert client.get("/api/v1/public/config").json()["whatsapp_live"] is False


def test_placeholder_outbound_stays_in_simulator_and_never_calls_meta(monkeypatch, http):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_token", "REPLACE_ME")
    monkeypatch.setattr(s, "whatsapp_phone_number_id", "REPLACE_ME")
    phone = fake_phone()
    with session_scope() as db:
        assert notify.send_customer_message(db, "+" + phone, "hello", channel="whatsapp") is True
    assert http.calls == []  # un-mocked behaviour would also have raised
    (m,) = out_messages(phone)
    assert m.provider == "simulator" and m.status == "SENT"


def test_sms_placeholder_provider_is_console(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "sms_provider", "REPLACE_ME")
    assert s.sms_provider_name == "console"


def test_config_summary_lists_names_only(monkeypatch, capsys):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_token", "FAKE_VALUE_MUST_NOT_APPEAR")
    monkeypatch.setattr(s, "whatsapp_app_secret", "REPLACE_ME")
    summary = s.channel_config_summary()
    assert "WHATSAPP_TOKEN" in summary["configured"] and "WHATSAPP_APP_SECRET" in summary["missing"]
    assert "FAKE_VALUE_MUST_NOT_APPEAR" not in json.dumps(summary)
    from weza.main import create_app
    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        create_app(start_worker=False)  # configure_logging() installs the JSON stdout handler
        out = capsys.readouterr().out
    finally:
        root.handlers[:] = saved  # don't leave a handler bound to pytest's captured stdout
    line = next(ln for ln in out.splitlines() if '"channel_config"' in ln)
    assert "FAKE_VALUE_MUST_NOT_APPEAR" not in out
    assert "WHATSAPP_TOKEN" in line and "WHATSAPP_APP_SECRET" in line  # names survive redaction (lists, not key/values)


# ------------------------------------------------------------------ GET verification


def test_verify_handshake_good_token_echoes_challenge(client, wa_inbound):
    r = client.get(URL, params={"hub.mode": "subscribe", "hub.verify_token": rw.FAKE_VERIFY_TOKEN, "hub.challenge": "98765"})
    assert r.status_code == 200 and r.text == "98765"


@pytest.mark.parametrize("token", ["wrong-token", ""])
def test_verify_handshake_bad_token_rejected(client, wa_inbound, token):
    r = client.get(URL, params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "1"})
    assert r.status_code == 403


def test_verify_handshake_wrong_mode_rejected(client, wa_inbound):
    r = client.get(URL, params={"hub.mode": "unsubscribe", "hub.verify_token": rw.FAKE_VERIFY_TOKEN, "hub.challenge": "1"})
    assert r.status_code == 403


# ------------------------------------------------------------------ POST signature


def test_post_valid_signature_accepted(client, wa_inbound):
    assert send(client, rw.build("status")).status_code == 200


def test_post_missing_signature_rejected(client, wa_inbound):
    assert send(client, rw.build("text", phone=fake_phone()), signature=None).status_code == 403


def test_post_invalid_signature_rejected_and_no_journey(client, wa_inbound):
    phone = fake_phone()
    assert send(client, rw.build("text", phone=phone), signature="sha256=" + "0" * 64).status_code == 403
    assert journeys_for(phone) == []


def test_post_signature_uses_constant_time_compare(client, wa_inbound, monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    send(client, rw.build("status"))
    assert calls, "signature must be checked with hmac.compare_digest"


def test_post_without_configured_secret_rejected(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", None)
    assert send(client, rw.build("status")).status_code == 403


# ------------------------------------------------------------------ inbound handling


def test_inbound_text_starts_journey_and_replies_via_simulator(client, wa_inbound):
    phone = fake_phone()
    assert text_msg(client, phone, "I need 5 million for stock for my shop").status_code == 200
    ((jid, node),) = journeys_for(phone)
    assert node == "CONFIRM_INTENT"
    outs = out_messages(phone)
    assert outs and all(m.provider == "simulator" for m in outs)


def test_followup_resumes_same_journey(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need money for school fees.")
    text_msg(client, phone, "2.5 million")
    ((jid, node),) = journeys_for(phone)
    assert node == "ASK_INTENT"  # customer type still unknown, same journey continued
    assert len(in_messages(jid)) == 2


def test_inbound_button_reply_advances_journey(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need 5 million for stock for my shop")
    assert send(client, rw.build("button", phone=phone, button_id="confirm")).status_code == 200
    ((jid, node),) = journeys_for(phone)
    assert node == "VERIFY_PHONE"


def test_duplicate_provider_message_id_processed_once(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need money for school fees.")
    mid = "wamid.FAKE_dup_reply"
    assert text_msg(client, phone, "2.5 million", mid).status_code == 200
    assert text_msg(client, phone, "2.5 million", mid).status_code == 200
    ((jid, _),) = journeys_for(phone)
    assert in_messages(jid).count(mid) == 1
    assert len(in_messages(jid)) == 2


def test_duplicate_of_first_message_processed_once(client, wa_inbound):
    phone = fake_phone()
    mid = "wamid.FAKE_dup_first"
    text_msg(client, phone, "I need money for school fees.", mid)
    n_out = len(out_messages(phone))
    text_msg(client, phone, "I need money for school fees.", mid)
    ((jid, _),) = journeys_for(phone)
    assert len(in_messages(jid)) == 1 and len(out_messages(phone)) == n_out


def test_unsupported_type_gets_graceful_reply_without_advancing_journey(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need money for school fees.")
    ((jid, node),) = journeys_for(phone)
    before = len(in_messages(jid))
    assert send(client, rw.build("unsupported", phone=phone)).status_code == 200
    assert journeys_for(phone) == [(jid, node)] and len(in_messages(jid)) == before
    assert "typed messages" in (out_messages(phone)[-1].body or "")


def test_status_only_payload_is_ok_and_creates_nothing(client, wa_inbound):
    phone = fake_phone()
    assert send(client, rw.build("status", phone=phone)).status_code == 200
    assert journeys_for(phone) == [] and out_messages(phone) == []


def test_rate_limit_applies_per_phone_on_simulator(client):
    phone = fake_phone()
    with session_scope() as db:
        for _ in range(40):
            rate_limit(db, f"wa:{idx_of(phone)}", 40, 600)
    r = client.post("/api/v1/channels/simulator/messages", json={"phone": "+" + phone, "text": "hello"})
    assert r.status_code == 429


def test_rate_limited_message_is_acknowledged_not_retried(client, wa_inbound):
    phone = fake_phone()
    with session_scope() as db:
        for _ in range(40):
            rate_limit(db, f"wa:{idx_of(phone)}", 40, 600)
    assert text_msg(client, phone, "hello").status_code == 200
    assert journeys_for(phone) == []  # dropped, not processed
    assert [(r.status, r.reason) for r in inbox_rows(phone)] == [("DROPPED", "RATE_LIMITED")]


def test_no_pii_in_logs(client, wa_inbound, caplog, capsys):
    phone = fake_phone()
    marker = "ZEBRA-MARKER-4471"
    with caplog.at_level(logging.DEBUG):
        text_msg(client, phone, f"I need money for {marker}")
        send(client, rw.build("unsupported", phone=phone))
        send(client, rw.build("text", phone=phone), signature="sha256=" + "0" * 64)
    blob = capsys.readouterr().out + " ".join(
        JsonFormatter().format(r) + r.getMessage() + str(getattr(r, "data", "")) for r in caplog.records)
    assert phone not in blob and marker not in blob and phone[3:] not in blob


# ------------------------------------------------------------------ outbound


def test_outbound_text_shape(wa_live, http):
    with session_scope() as db:
        assert notify.send_customer_message(db, "+" + fake_phone(), "Hello there", channel="whatsapp")
    (c,) = http.calls
    assert c["url"].startswith("https://graph.facebook.com/v21.0/000000000000000/messages")
    assert c["headers"]["Authorization"] == "Bearer FAKE_token_not_real"
    assert c["json"]["type"] == "text" and c["json"]["text"]["body"] == "Hello there"
    assert not c["json"]["to"].startswith("+")


def test_outbound_uses_configured_api_version(wa_live, http, monkeypatch):
    monkeypatch.setattr(wa_live, "whatsapp_api_version", "v23.0")
    with session_scope() as db:
        notify.send_customer_message(db, "+" + fake_phone(), "x", channel="whatsapp")
    assert "/v23.0/" in http.calls[0]["url"]


def test_outbound_buttons_become_interactive_message(wa_live, http):
    qr = [{"label": "Yes, that's right and a very long label", "action": "confirm"},
          {"label": "Change it", "action": "select", "value": "abc"}]
    with session_scope() as db:
        notify.send_customer_message(db, "+" + fake_phone(), "Is this right?", channel="whatsapp",
                                     payload={"quick_replies": qr})
    msg = http.calls[0]["json"]
    assert msg["type"] == "interactive"
    buttons = msg["interactive"]["action"]["buttons"]
    assert [b["reply"]["id"] for b in buttons] == ["confirm", "select:abc"]
    assert all(len(b["reply"]["title"]) <= 20 for b in buttons)


def test_outbound_more_than_three_buttons_falls_back_to_text(wa_live, http):
    qr = [{"label": f"Option {i}", "action": "pick", "value": str(i)} for i in range(4)]
    with session_scope() as db:
        notify.send_customer_message(db, "+" + fake_phone(), "Choose", channel="whatsapp", payload={"quick_replies": qr})
    msg = http.calls[0]["json"]
    assert msg["type"] == "text" and "Reply with: Option 0 / Option 1 / Option 2 / Option 3" in msg["text"]["body"]


@pytest.mark.parametrize("behaviour", ["http500", "timeout"])
def test_provider_failure_is_recorded_and_journey_continues(client, wa_live, http, behaviour):
    http.behaviour = behaviour
    phone = fake_phone()
    assert text_msg(client, phone, "I need 5 million for stock for my shop").status_code == 200
    ((jid, node),) = journeys_for(phone)
    assert node == "CONFIRM_INTENT"
    outs = out_messages(phone)
    assert outs and all(m.provider == "whatsapp_cloud" and m.status == "FAILED" for m in outs)
    with session_scope() as db:
        assert db.execute(select(func.count()).select_from(GraphInstance).where(GraphInstance.id == jid)).scalar_one() == 1


def test_provider_success_is_recorded_as_sent(client, wa_live, http):
    phone = fake_phone()
    text_msg(client, phone, "I need 5 million for stock for my shop")
    outs = out_messages(phone)
    assert outs and all(m.provider == "whatsapp_cloud" and m.status == "SENT" for m in outs)
    assert http.calls, "configured outbound should call the (mocked) Graph API"


# ------------------------------------------------------------------ delivery status callbacks (step b)


def _live_conversation(client, phone):
    text_msg(client, phone, "I need 5 million for stock for my shop")
    return [m for m in out_messages(phone) if m.provider_message_id]


def test_outbound_records_provider_message_id(client, wa_live):
    phone = fake_phone()
    sent = _live_conversation(client, phone)
    assert sent and all(m.provider_message_id.startswith("wamid.FAKE_OUT_") for m in sent)
    assert len({m.provider_message_id for m in sent}) == len(sent)


def test_status_callbacks_update_message_and_do_not_touch_journey(client, wa_live):
    phone = fake_phone()
    (m, *_) = _live_conversation(client, phone)
    ((jid, node),) = journeys_for(phone)
    n_in, n_out = len(in_messages(jid)), len(out_messages(phone))
    wamid = m.provider_message_id
    for st in ("sent", "delivered", "read"):
        payload = rw.status_payload(wamid, st, phone)
        assert send(client, payload).status_code == 200
        got = next(x for x in out_messages(phone) if x.provider_message_id == wamid)
        assert got.provider_status == st and got.status_at is not None
    # out-of-order retry of an older status must not move the state backwards
    send(client, rw.status_payload(wamid, "delivered", phone))
    assert next(x for x in out_messages(phone) if x.provider_message_id == wamid).provider_status == "read"
    assert journeys_for(phone) == [(jid, node)] and len(in_messages(jid)) == n_in and len(out_messages(phone)) == n_out


def test_failed_status_stores_error_code(client, wa_live):
    phone = fake_phone()
    (m, *_) = _live_conversation(client, phone)
    assert send(client, rw.status_payload(m.provider_message_id, "failed", phone, error_code=131026)).status_code == 200
    got = next(x for x in out_messages(phone) if x.provider_message_id == m.provider_message_id)
    assert got.provider_status == "failed" and got.error_code == "131026" and got.status == "FAILED"


def test_failed_status_does_not_override_delivered(client, wa_live):
    phone = fake_phone()
    (m, *_) = _live_conversation(client, phone)
    send(client, rw.status_payload(m.provider_message_id, "delivered", phone))
    send(client, rw.status_payload(m.provider_message_id, "failed", phone, error_code=131026))
    got = next(x for x in out_messages(phone) if x.provider_message_id == m.provider_message_id)
    assert got.provider_status == "delivered" and got.error_code is None


def test_status_for_unknown_message_is_ignored(client, wa_inbound):
    assert send(client, rw.status_payload("wamid.FAKE_UNKNOWN", "delivered")).status_code == 200


def test_unknown_status_value_is_ignored(client, wa_live):
    phone = fake_phone()
    (m, *_) = _live_conversation(client, phone)
    assert send(client, rw.status_payload(m.provider_message_id, "weird", phone)).status_code == 200
    got = next(x for x in out_messages(phone) if x.provider_message_id == m.provider_message_id)
    assert got.provider_status is None


# ------------------------------------------------------------------ inbound hardening (step c)


def test_webhook_acknowledges_before_processing(client, wa_inbound):
    phone = fake_phone()
    assert text_msg(client, phone, "I need 5 million for stock for my shop", process=False).status_code == 200
    assert journeys_for(phone) == [] and [r.status for r in inbox_rows(phone)] == ["PENDING"]
    drain()
    assert [r.status for r in inbox_rows(phone)] == ["DONE"] and len(journeys_for(phone)) == 1


def test_inbox_keeps_no_plaintext_and_wipes_after_processing(client, wa_inbound):
    phone, marker = fake_phone(), "ZEBRA-MARKER-9921"
    text_msg(client, phone, f"I need money for {marker}", process=False)
    (row,) = inbox_rows(phone)
    assert row.payload_enc and marker not in row.payload_enc and phone not in row.payload_enc
    drain()
    assert inbox_rows(phone)[0].payload_enc is None


def test_provider_retry_of_same_message_creates_one_inbox_row(client, wa_inbound):
    phone = fake_phone()
    payload = rw.build("text", phone=phone, message_id="wamid.FAKE_retry_1")
    for _ in range(3):
        assert send(client, payload, process=False).status_code == 200
    assert len(inbox_rows(phone)) == 1
    drain()
    assert len(journeys_for(phone)) == 1


@pytest.mark.parametrize("kind", ["image", "audio", "video", "document", "sticker", "location", "contacts"])
def test_each_unsupported_type_gets_the_polite_reply(client, wa_inbound, kind):
    phone = fake_phone()
    p = rw.message_payload({"id": f"wamid.FAKE_{kind}_{phone}", "type": kind, kind: {"id": "FAKE"}}, phone)
    assert send(client, p).status_code == 200
    assert journeys_for(phone) == []
    (m,) = out_messages(phone)
    assert m.body == "Sorry, I can only read typed messages and button taps for now. " \
                     "Please type your message or tap one of the options."
    assert inbox_rows(phone)[0].reason == "UNSUPPORTED_TYPE"


def test_unsupported_replies_are_capped_per_number(client, wa_inbound):
    phone = fake_phone()
    for i in range(6):
        send(client, rw.message_payload({"id": f"wamid.FAKE_img_{phone}_{i}", "type": "image", "image": {}}, phone))
    assert len(out_messages(phone)) == 3 and len(inbox_rows(phone)) == 6


def test_reaction_is_ignored_without_reply(client, wa_inbound):
    phone = fake_phone()
    p = rw.message_payload({"id": f"wamid.FAKE_react_{phone}", "type": "reaction", "reaction": {"emoji": "x"}}, phone)
    assert send(client, p).status_code == 200
    assert journeys_for(phone) == [] and out_messages(phone) == []
    assert inbox_rows(phone)[0].status == "IGNORED"


def test_messages_are_processed_in_arrival_order(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need money for school fees.", mid=f"wamid.FAKE_o1_{phone}", process=False)
    text_msg(client, phone, "2.5 million", mid=f"wamid.FAKE_o2_{phone}", process=False)
    drain()
    ((jid, node),) = journeys_for(phone)
    assert node == "ASK_INTENT" and len(in_messages(jid)) == 2
    a, b = inbox_rows(phone)
    assert a.processed_at <= b.processed_at


def test_malformed_payloads_do_not_crash(client, wa_inbound):
    assert post_raw(client, b"not json").status_code == 422
    assert post_raw(client, b"[1,2]").status_code == 422
    junk = {"entry": [{"changes": [{"value": {"messages": ["x", {"type": "text"}, {"id": "w", "from": ""}]}},
                                    {"value": None}, {}]}, {}]}
    assert send(client, junk).status_code == 200


def test_one_bad_message_in_a_batch_does_not_block_the_others(client, wa_inbound):
    phone = fake_phone()
    good = rw.message_payload({"id": f"wamid.FAKE_good_{phone}", "type": "text", "text": {"body": "hi there friend"}}, phone)
    good["entry"][0]["changes"][0]["value"]["messages"].insert(0, {"type": "text"})  # no id/from
    assert send(client, good).status_code == 200
    assert len(inbox_rows(phone)) == 1 and len(journeys_for(phone)) == 1


def test_processing_failure_keeps_message_pending_for_retry(client, wa_inbound, monkeypatch):
    from weza.api.v1 import public
    phone = fake_phone()

    def boom(*a, **k):
        raise RuntimeError("simulated crash")
    monkeypatch.setattr(public, "inbound", boom)
    assert text_msg(client, phone, "I need 5 million for stock for my shop").status_code == 200
    assert [r.status for r in inbox_rows(phone)] == ["PENDING"] and journeys_for(phone) == []
