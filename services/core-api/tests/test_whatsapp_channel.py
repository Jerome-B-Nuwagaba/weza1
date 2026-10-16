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
import re
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from scripts import replay_whatsapp_webhook as rw
from weza.config import DEFAULT_GRAPH_API_VERSION, get_settings, is_configured
from weza.domains.customer import documents as docs
from weza.domains.customer.models import Document
from weza.domains.intelligence.parsing import parse_phone
from weza.domains.misc_models import ChannelMessage, WhatsappInbox
from weza.domains.need.models import ConversationMessage
from weza.domains.notification import service as notify
from weza.domains.notification import whatsapp_inbound as wa_in
from weza.platform import crypto
from weza.platform.controls import rate_limit
from weza.platform.db import session_scope, utcnow
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
        self.media: dict[str, tuple[bytes, str]] = {}  # media id -> (bytes, mime)
        self.media_mode = "ok"  # ok | fail
        self.media_host = "https://lookaside.fbsbx.com/fake/"
        self.gets: list[str] = []

    def get(self, url, headers=None, timeout=None, **kw):
        self.gets.append(url)
        req = httpx.Request("GET", url)
        if self.media_mode == "fail":
            raise httpx.ConnectError("fake")
        mid = url.rsplit("/", 1)[1]
        if mid not in self.media:
            return httpx.Response(404, json={}, request=req)
        data, mime = self.media[mid]
        if url.startswith("https://graph.facebook.com/"):
            return httpx.Response(200, json={"url": self.media_host + mid, "mime_type": mime, "file_size": len(data)},
                                  request=req)
        return httpx.Response(200, content=data, request=req)

    def __call__(self, url, json=None, headers=None, timeout=None, **kw):
        if self.behaviour == "unexpected":
            raise AssertionError("real network call attempted")
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.behaviour == "timeout":
            raise httpx.ConnectTimeout("fake timeout")
        if self.behaviour == "read_timeout":  # request sent, no answer: Meta may have accepted it
            raise httpx.ReadTimeout("fake read timeout")
        self.n += 1
        req = httpx.Request("POST", url)
        errors = {"http500": (500, 0), "http429": (429, 130429), "http400": (400, 131030),
                  "http131047": (400, 131047), "http190": (401, 190), "http131056": (400, 131056)}
        if self.behaviour in errors:
            code, err = errors[self.behaviour]
            return httpx.Response(code, json={"error": {"code": err, "message": "fake"}} if err else {}, request=req)
        return httpx.Response(200, json={"messages": [{"id": f"wamid.FAKE_OUT_{next(_wamid)}"}]}, request=req)


@pytest.fixture(autouse=True)
def http(monkeypatch):
    rec = Http()
    monkeypatch.setattr(httpx, "post", rec)
    monkeypatch.setattr(httpx, "get", rec.get)
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
    assert c["url"].startswith(f"https://graph.facebook.com/{DEFAULT_GRAPH_API_VERSION}/000000000000000/messages")
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


@pytest.mark.parametrize("kind", ["audio", "video", "sticker", "location", "contacts"])
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
        send(client, rw.message_payload({"id": f"wamid.FAKE_img_{phone}_{i}", "type": "audio", "audio": {}}, phone))
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


# ------------------------------------------------------------------ outbound failures and retries (step d)


def _send_one(phone, body="Your request is moving along."):
    with session_scope() as db:
        return notify.send_customer_message(db, "+" + phone, body, channel="whatsapp", kind="test")


def _retry_sweep(minutes=2):
    with session_scope() as db:
        return notify.retry_failed_channel_messages(db, now=utcnow() + timedelta(minutes=minutes))


@pytest.mark.parametrize("behaviour,code,retryable", [("http429", "130429", True), ("http500", "HTTP_500", True),
                                                      ("timeout", "NETWORK", True), ("http400", "131030", False)])
def test_failure_classification_and_recording(wa_live, http, behaviour, code, retryable):
    http.behaviour = behaviour
    phone = fake_phone()
    assert _send_one(phone) is False
    (m,) = out_messages(phone)
    assert m.status == "FAILED" and m.provider == "whatsapp_cloud" and m.error_code == code
    assert m.provider_message_id is None
    assert ("_retry_to" in m.payload) is retryable


def test_retryable_failure_is_resent_by_the_sweep_and_recorded(wa_live, http):
    http.behaviour = "http500"
    phone = fake_phone()
    _send_one(phone)
    _retry_sweep(minutes=0)  # backoff: not due yet
    assert out_messages(phone)[0].status == "FAILED"
    http.behaviour = "ok"
    _retry_sweep()
    (m,) = out_messages(phone)
    assert m.status == "SENT" and m.error_code is None and m.provider_message_id.startswith("wamid.FAKE_OUT_")
    assert "_retry_to" not in m.payload
    n = http.n
    _retry_sweep()
    assert http.n == n  # nothing left to retry for this message


def test_retries_are_capped(wa_live, http):
    http.behaviour = "http500"
    phone = fake_phone()
    _send_one(phone)
    for minutes in (2, 10, 20, 25):
        _retry_sweep(minutes=minutes)
    (m,) = out_messages(phone)
    assert m.status == "FAILED" and "_retry_to" not in m.payload
    assert len(http.calls) >= 3 and "_retry_to" not in m.payload  # initial send + retries, then it gives up


def test_stale_failed_messages_are_not_retried(wa_live, http):
    http.behaviour = "http500"
    phone = fake_phone()
    _send_one(phone)
    http.behaviour = "ok"
    with session_scope() as db:
        notify.retry_failed_channel_messages(db, now=utcnow() + timedelta(hours=2))
    assert out_messages(phone)[0].status == "FAILED"


def test_permanent_failure_is_not_retried(wa_live, http):
    http.behaviour = "http400"
    phone = fake_phone()
    _send_one(phone)
    http.behaviour = "ok"
    _retry_sweep()
    assert out_messages(phone)[0].status == "FAILED" and out_messages(phone)[0].error_code == "131030"


def test_outbound_failure_logs_carry_no_pii(wa_live, http, caplog, capsys):
    http.behaviour = "http500"
    phone, body = fake_phone(), "Secret body ZEBRA-MARKER-5512"
    with caplog.at_level(logging.DEBUG):
        _send_one(phone, body)
        _retry_sweep()
    blob = capsys.readouterr().out + " ".join(
        JsonFormatter().format(r) + r.getMessage() + str(getattr(r, "data", "")) for r in caplog.records)
    assert phone not in blob and phone[3:] not in blob and "ZEBRA-MARKER-5512" not in blob
    assert any(r.getMessage() == "whatsapp_send_failed" for r in caplog.records)


# ------------------------------------------------------------------ SMS / OTP adapter slot (step e)


class FakeSms:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def __call__(self, settings):
        return self

    def send(self, to, body):
        self.sent.append((to, body))
        return notify.SendResult(self.ok, provider_message_id="sms-FAKE-1" if self.ok else None,
                                 error_code=None if self.ok else "FAKE_ERR")


@pytest.fixture()
def sms_registry(monkeypatch):
    from weza.domains.notification import sms
    monkeypatch.setattr(sms, "_PROVIDERS", {})
    return sms


def _sms(phone, body="Your WEZA verification code is 123456.", kind="otp"):
    with session_scope() as db:
        return notify.send_customer_message(db, "+" + phone, body, channel="sms", kind=kind)


def test_sms_console_default_goes_to_simulator_with_code_visible():
    phone = fake_phone()
    assert _sms(phone) is True
    (m,) = out_messages(phone)
    assert m.provider == "simulator" and "123456" in m.body


def test_sms_provider_sends_and_never_stores_the_otp(sms_registry, monkeypatch):
    s = get_settings()
    fake = FakeSms()
    sms_registry.register_sms_provider("fakesms", fake)
    monkeypatch.setattr(s, "sms_provider", "fakesms")
    monkeypatch.setattr(s, "sms_api_key", "FAKE_key_not_real")
    phone = fake_phone()
    assert _sms(phone) is True
    assert fake.sent == [("+" + phone, "Your WEZA verification code is 123456.")]
    (m,) = out_messages(phone)
    assert m.provider == "fakesms" and m.status == "SENT" and m.provider_message_id == "sms-FAKE-1"
    assert "123456" not in m.body


def test_sms_provider_failure_is_recorded(sms_registry, monkeypatch):
    s = get_settings()
    sms_registry.register_sms_provider("fakesms", FakeSms(ok=False))
    monkeypatch.setattr(s, "sms_provider", "fakesms")
    monkeypatch.setattr(s, "sms_api_key", "FAKE_key_not_real")
    phone = fake_phone()
    assert _sms(phone) is False
    (m,) = out_messages(phone)
    assert m.status == "FAILED" and m.error_code == "FAKE_ERR"


def test_sms_provider_crash_does_not_raise(sms_registry, monkeypatch):
    class Crash:
        def __init__(self, s): ...
        def send(self, *a):
            raise RuntimeError("boom")
    s = get_settings()
    sms_registry.register_sms_provider("fakesms", Crash)
    monkeypatch.setattr(s, "sms_provider", "fakesms")
    monkeypatch.setattr(s, "sms_api_key", "FAKE_key_not_real")
    phone = fake_phone()
    assert _sms(phone) is False and out_messages(phone)[0].error_code == "PROVIDER_ERROR"


def test_sms_placeholder_key_means_provider_not_called(sms_registry, monkeypatch):
    s = get_settings()
    fake = FakeSms()
    sms_registry.register_sms_provider("fakesms", fake)
    monkeypatch.setattr(s, "sms_provider", "fakesms")
    monkeypatch.setattr(s, "sms_api_key", "REPLACE_ME")
    monkeypatch.setattr(s, "env", "production")
    phone = fake_phone()
    assert _sms(phone) is False and fake.sent == []
    assert out_messages(phone)[0].error_code == "NOT_CONFIGURED"


def test_sms_unimplemented_provider_fails_in_production_but_falls_back_in_dev(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "sms_provider", "someprovider")
    monkeypatch.setattr(s, "sms_api_key", "FAKE_key_not_real")
    dev = fake_phone()
    assert _sms(dev) is True and out_messages(dev)[0].provider == "simulator"
    monkeypatch.setattr(s, "env", "production")
    prod = fake_phone()
    assert _sms(prod) is False
    (m,) = out_messages(prod)
    assert m.status == "FAILED" and m.error_code == "PROVIDER_NOT_IMPLEMENTED" and "123456" not in m.body


def test_otp_journey_still_shows_dev_code_and_uses_provider(client, journey, sms_registry, monkeypatch):
    s = get_settings()
    fake = FakeSms()
    sms_registry.register_sms_provider("fakesms", fake)
    monkeypatch.setattr(s, "sms_provider", "fakesms")
    monkeypatch.setattr(s, "sms_api_key", "FAKE_key_not_real")
    j = journey("I need UGX 30 million to expand my pharmacy.")
    j.send(action="confirm")
    j.send("0772100777")
    code = j.cards("otp_input")[0]["dev_code"]  # dev mode (OTP_DELIVERY=display) still shows it
    assert code and fake.sent and code in fake.sent[0][1]
    j.send(code)
    assert j.node == "ASK_PROFILE"


def test_config_summary_flags_unreachable_otp_in_production(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "env", "production")
    assert s.channel_config_summary()["verification_sms"] is False


# ------------------------------------------------------------------ landing "Continue on WhatsApp" (step f)


@pytest.mark.parametrize("raw,expected", [("+256 772 000 111", "256772000111"), ("256772000111", "256772000111"),
                                          ("REPLACE_ME", None), ("", None), (None, None), ("12345", None),
                                          ("not a number", None)])
def test_public_config_exposes_business_number_digits_only(client, monkeypatch, raw, expected):
    monkeypatch.setattr(get_settings(), "whatsapp_business_number", raw)
    assert client.get("/api/v1/public/config").json()["whatsapp_number"] == expected


# ------------------------------------------------------------------ OTP through the Meta WhatsApp API


@pytest.fixture()
def otp_wa(wa_live, monkeypatch):
    """SMS_PROVIDER=whatsapp: verification codes go out through the (mocked) Cloud API."""
    monkeypatch.setattr(wa_live, "sms_provider", "whatsapp")
    return wa_live


def test_whatsapp_otp_free_form_when_no_template(otp_wa, http):
    phone = fake_phone()
    assert _sms(phone, "Your WEZA verification code is 482913. It expires in 5 minutes.") is True
    (c,) = http.calls
    assert c["json"]["type"] == "text" and "482913" in c["json"]["text"]["body"]
    (m,) = out_messages(phone)
    assert m.channel == "sms" and m.provider == "whatsapp" and m.status == "SENT"
    assert m.provider_message_id.startswith("wamid.FAKE_OUT_") and "482913" not in m.body


def test_whatsapp_otp_uses_authentication_template_when_configured(otp_wa, http, monkeypatch):
    monkeypatch.setattr(otp_wa, "whatsapp_otp_template_name", "weza_login_code")
    monkeypatch.setattr(otp_wa, "whatsapp_otp_template_language", "en")
    phone = fake_phone()
    assert _sms(phone, "Your WEZA verification code is 482913. It expires in 5 minutes.") is True
    msg = http.calls[0]["json"]
    assert msg["type"] == "template" and msg["template"]["name"] == "weza_login_code"
    assert msg["template"]["language"] == {"code": "en"} and msg["to"] == phone
    body_param, button = msg["template"]["components"]
    assert body_param["parameters"][0]["text"] == "482913"
    assert button["sub_type"] == "url" and button["parameters"][0]["text"] == "482913"


def test_whatsapp_otp_outside_window_fails_honestly(otp_wa, http):
    http.behaviour = "http131047"
    phone = fake_phone()
    assert _sms(phone) is False
    (m,) = out_messages(phone)
    assert m.status == "FAILED" and m.error_code == "131047" and "123456" not in m.body


def test_whatsapp_otp_not_configured_fails_in_production_and_falls_back_in_dev(wa_inbound, monkeypatch, http):
    monkeypatch.setattr(wa_inbound, "sms_provider", "whatsapp")  # no token / phone id => not ready
    dev = fake_phone()
    assert _sms(dev) is True and out_messages(dev)[0].provider == "simulator"
    monkeypatch.setattr(wa_inbound, "env", "production")
    prod = fake_phone()
    assert _sms(prod) is False and out_messages(prod)[0].error_code == "NOT_CONFIGURED"
    assert http.calls == []


def test_otp_journey_via_whatsapp_provider(client, journey, otp_wa, http):
    j = journey("I need UGX 30 million to expand my pharmacy.")
    j.send(action="confirm")
    j.send("0772100888")
    code = j.cards("otp_input")[0]["dev_code"]
    sent = [c["json"] for c in http.calls if "verification code" in json.dumps(c["json"])]
    assert code and sent and code in sent[0]["text"]["body"]
    j.send(code)
    assert j.node == "ASK_PROFILE"


# ------------------------------------------------------------------ photos and documents over WhatsApp

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes" * 8
PDF = b"%PDF-1.4\n" + b"fake-pdf-bytes" * 8


def media_msg(client, phone, kind, media_id, **fields):
    body = {"id": media_id, "mime_type": "image/png" if kind == "image" else "application/pdf", **fields}
    return send(client, rw.message_payload({"id": f"wamid.FAKE_{kind}_{media_id}_{phone}_{next(_wamid)}", "type": kind, kind: body}, phone))


def verified_journey(client, phone) -> dict:
    """Walk a WhatsApp journey through OTP verification; returns {'id', 'customer_id'}."""
    text_msg(client, phone, "I need 5 million for stock for my shop")
    send(client, rw.build("button", phone=phone, button_id="confirm"))
    text_msg(client, phone, "0" + phone[3:])
    otp = next(re.search(r"code is (\d{6})", m.body).group(1) for m in reversed(out_messages(phone))
               if m.channel == "sms" and "verification code" in m.body)
    text_msg(client, phone, otp)
    ((jid, node),) = journeys_for(phone)
    with session_scope() as db:
        cid = db.get(GraphInstance, jid).state.get("customer_id")
    assert node == "ASK_PROFILE" and cid
    return {"id": jid, "customer_id": cid}


def stored_docs(customer_id):
    with session_scope() as db:
        rows = db.execute(select(Document).where(Document.customer_id == customer_id)).scalars().all()
        db.expunge_all()
        return rows


def last_reply(phone) -> str:
    return [m for m in out_messages(phone) if m.channel == "whatsapp"][-1].body


@pytest.mark.parametrize("raw,expected", [("my payslip", "payslip"), ("March bank statement", "bank_statement"),
                                          ("MTN MoMo statement", "mobile_money_statement"),
                                          ("front of my ID", "national_id"), ("trading licence", "trading_licence"),
                                          ("here you go", "other"), (None, "other")])
def test_guess_doc_type_from_caption(raw, expected):
    assert wa_in.guess_doc_type(raw, None, []) == expected


def test_guess_doc_type_falls_back_to_first_outstanding():
    assert wa_in.guess_doc_type("here", "scan001.pdf", ["bank_statement", "payslip"]) == "bank_statement"
    assert wa_in.guess_doc_type("my payslip", None, ["bank_statement"]) == "payslip"


def test_media_without_a_journey_gets_guidance(client, wa_live, http):
    phone = fake_phone()
    http.media["M1"] = (PNG, "image/png")
    assert media_msg(client, phone, "image", "M1").status_code == 200
    assert journeys_for(phone) == [] and "tell me what financing" in last_reply(phone)
    assert http.gets == []  # nothing downloaded for someone who has no request


def test_media_before_phone_verification_is_not_stored(client, wa_live, http):
    phone = fake_phone()
    text_msg(client, phone, "I need 5 million for stock for my shop")
    http.media["M2"] = (PNG, "image/png")
    media_msg(client, phone, "image", "M2")
    assert "verifying your phone number" in last_reply(phone) and http.gets == []


def test_photo_is_downloaded_scanned_stored_encrypted_and_acknowledged(client, wa_live, http):
    phone = fake_phone()
    j = verified_journey(client, phone)
    http.media["M3"] = (PNG, "image/png")
    assert media_msg(client, phone, "image", "M3", caption="my payslip").status_code == 200
    (d,) = stored_docs(j["customer_id"])
    assert d.doc_type == "payslip" and d.pipeline_state == "STORED" and d.mime == "image/png"
    assert d.scan_result.endswith("clean") and d.size == len(PNG)
    with session_scope() as db:
        assert docs.read_bytes(db, d.id) == PNG
    assert "saved your recent payslip" in last_reply(phone)
    assert http.gets[0].endswith("/M3") and http.gets[1].startswith("https://lookaside.fbsbx.com/")
    assert any("Document sent" in str(x) for x in in_messages_text(j["id"]))
    assert [r.reason for r in inbox_rows(phone)][-1] == "DOC_STORED"


def in_messages_text(journey_id):
    with session_scope() as db:
        return [m.content for m in db.execute(select(ConversationMessage).where(
            ConversationMessage.session_id == journey_id, ConversationMessage.direction == "IN")).scalars()]


def test_pdf_document_with_filename_is_stored(client, wa_live, http):
    phone = fake_phone()
    j = verified_journey(client, phone)
    http.media["M4"] = (PDF, "application/pdf")
    media_msg(client, phone, "document", "M4", filename="Bank statement March.pdf")
    (d,) = stored_docs(j["customer_id"])
    assert d.doc_type == "bank_statement" and d.mime == "application/pdf" and d.filename == "Bank statement March.pdf"


def test_malware_signature_is_rejected_and_not_kept(client, wa_live, http):
    phone = fake_phone()
    j = verified_journey(client, phone)
    http.media["M5"] = (b"%PDF-" + docs.EICAR, "application/pdf")
    media_msg(client, phone, "document", "M5", filename="x.pdf")
    (d,) = stored_docs(j["customer_id"])
    assert d.pipeline_state == "REJECTED"
    with session_scope() as db:
        assert docs.read_bytes(db, d.id) is None
    assert "security check" in last_reply(phone)


def test_unsupported_file_format_is_rejected_politely(client, wa_live, http):
    phone = fake_phone()
    j = verified_journey(client, phone)
    http.media["M6"] = (b"RIFF....WEBPxxxxxxxx", "image/webp")
    media_msg(client, phone, "image", "M6")
    assert stored_docs(j["customer_id"])[0].pipeline_state == "REJECTED"
    assert "PDF, JPG or PNG" in last_reply(phone)


@pytest.mark.parametrize("mode", ["unknown_id", "network"])
def test_download_failure_asks_to_resend_and_does_not_block(client, wa_live, http, mode):
    phone = fake_phone()
    j = verified_journey(client, phone)
    http.media_mode = "fail" if mode == "network" else "ok"
    media_msg(client, phone, "image", "NOPE")
    assert "couldn't download" in last_reply(phone) and stored_docs(j["customer_id"]) == []
    assert inbox_rows(phone)[-1].status == "DONE"
    http.media_mode = "ok"
    http.media["M7"] = (PNG, "image/png")
    media_msg(client, phone, "image", "M7")  # the next upload works
    assert len(stored_docs(j["customer_id"])) == 1


def test_media_url_must_be_https_and_not_an_ip(client, wa_live, http):
    phone = fake_phone()
    j = verified_journey(client, phone)
    http.media["M8"] = (PNG, "image/png")
    for host in ("http://lookaside.fbsbx.com/fake/", "https://127.0.0.1/fake/", "https://localhost/fake/"):
        http.media_host = host
        media_msg(client, phone, "image", "M8")
    assert stored_docs(j["customer_id"]) == [] and len(http.gets) == 3  # only the Graph metadata calls


def test_oversized_media_is_refused_before_download(client, wa_live, http, monkeypatch):
    phone = fake_phone()
    j = verified_journey(client, phone)
    monkeypatch.setattr("weza.domains.notification.whatsapp_media.MAX_BYTES", 10)
    http.media["M9"] = (PNG, "image/png")
    media_msg(client, phone, "image", "M9")
    assert "larger than 10 MB" in last_reply(phone) and stored_docs(j["customer_id"]) == []
    assert len(http.gets) == 1


def test_media_uploads_are_rate_limited(client, wa_live, http):
    phone = fake_phone()
    verified_journey(client, phone)
    with session_scope() as db:
        for _ in range(10):
            rate_limit(db, f"wa:media:{idx_of(phone)}", 10, 600)
    http.media["M10"] = (PNG, "image/png")
    media_msg(client, phone, "image", "M10")
    assert inbox_rows(phone)[-1].reason == "RATE_LIMITED" and http.gets == []


def test_media_logs_carry_no_pii_or_tokens(client, wa_live, http, caplog, capsys):
    phone = fake_phone()
    verified_journey(client, phone)
    capsys.readouterr()
    http.media["M11"] = (PNG, "image/png")
    with caplog.at_level(logging.DEBUG):
        media_msg(client, phone, "image", "M11", caption="my ZEBRA-MARKER-7731 payslip")
        http.media_mode = "fail"
        media_msg(client, phone, "image", "M12")
    blob = capsys.readouterr().out + " ".join(
        JsonFormatter().format(r) + r.getMessage() + str(getattr(r, "data", "")) for r in caplog.records)
    for secret in (phone, phone[3:], "ZEBRA-MARKER-7731", "FAKE_token_not_real", "M11", "lookaside"):
        assert secret not in blob


def test_missing_item_journey_resumes_when_document_arrives(client, wa_live, http, monkeypatch):
    """A journey waiting at REQUEST_MISSING_ITEM is resumed (READINESS_CHECK re-run) by a WhatsApp upload."""
    from weza.domains.need import service as journeys_svc
    phone = fake_phone()
    j = verified_journey(client, phone)
    resumed = []
    monkeypatch.setattr(journeys_svc, "system_resume", lambda db, jid, action, *a, **k: resumed.append((str(jid), action)))
    with session_scope() as db:
        gi = db.get(GraphInstance, j["id"])
        gi.current_node, gi.status = "REQUEST_MISSING_ITEM", "WAITING"
    http.media["M13"] = (PDF, "application/pdf")
    media_msg(client, phone, "document", "M13", filename="payslip.pdf")
    assert resumed == [(j["id"], "document_uploaded")]


# ------------------------------------------------------------------ web -> WhatsApp hand-over (acquisition reference)


def test_parse_ref_marker():
    text, attr = wa_in.split_ref("I need UGX 5 million for stock\n(ref:qr~Q4SME~partner1~friend)")
    assert text == "I need UGX 5 million for stock"
    assert attr == {"src": "qr", "cmp": "Q4SME", "ptn": "partner1", "ref": "friend"}
    assert wa_in.split_ref("Hi\n(ref:~~~)") == ("Hi", {})
    assert wa_in.split_ref("plain message") == ("plain message", {})
    assert wa_in.split_ref("(ref:<script>)") == ("(ref:<script>)", {})  # invalid characters: left untouched


def test_first_whatsapp_message_records_web_attribution_and_strips_marker(client, wa_inbound):
    from weza.domains.commercial.models import Attribution
    phone = fake_phone()
    campaign = f"CMP{phone[-5:]}"
    text_msg(client, phone, f"I need 5 million for stock for my shop\n(ref:landing~{campaign}~~)")
    ((jid, node),) = journeys_for(phone)
    assert node == "CONFIRM_INTENT"  # the need was understood without the marker getting in the way
    with session_scope() as db:
        a = db.execute(select(Attribution).where(Attribution.campaign_code == campaign)).scalar_one()
        assert a.source == "landing" and a.channel == "whatsapp"
    first = in_messages_text(jid)[0]
    assert "(ref:" not in json.dumps(first)


# ------------------------------------------------------------------ go-live hardening


def _reviews(kind: str) -> list:
    from weza.domains.misc_models import ReviewItem
    with session_scope() as db:
        rows = db.execute(select(ReviewItem).where(ReviewItem.kind == kind)).scalars().all()
        db.expunge_all()
        return rows


def _inbox_retry(minutes: float = 0):
    with session_scope() as db:
        return wa_in.retry_pending(db, now=utcnow() + timedelta(minutes=minutes))


def test_coexistence_echoes_and_history_are_never_routed_to_the_agent(client, wa_inbound):
    """WhatsApp Business app coexistence sends staff replies (smb_message_echoes) and chat history to the same
    webhook. They must not start or advance a customer journey."""
    phone = fake_phone()
    for field in ("smb_message_echoes", "history", "smb_app_state_sync", "message_template_status_update"):
        p = rw.build("text", phone=phone, text="I need 5 million for stock for my shop")
        p["entry"][0]["changes"][0]["field"] = field
        assert send(client, p).status_code == 200
    assert inbox_rows(phone) == [] and journeys_for(phone) == [] and out_messages(phone) == []


def test_messages_for_another_business_number_are_skipped(client, wa_live):
    phone = fake_phone()
    p = rw.build("text", phone=phone, text="I need 5 million for stock for my shop")
    p["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "999999999999999"
    assert send(client, p).status_code == 200
    assert inbox_rows(phone) == [] and journeys_for(phone) == []
    text_msg(client, phone, "I need 5 million for stock for my shop")  # same message to OUR number is answered
    assert len(journeys_for(phone)) == 1 and out_messages(phone)


def test_structurally_odd_signed_payloads_are_acknowledged(client, wa_inbound):
    for junk in ({"entry": {"changes": []}}, {"entry": [{"changes": "x"}]},
                 {"entry": [{"changes": [{"field": "messages", "value": {"statuses": [{"id": "w", "status": "read",
                                                                                      "errors": "bad"}]}}]}]},
                 {"entry": [{"changes": [{"field": "messages", "value": {"messages": {"not": "a list"}}}]}]}):
        assert send(client, junk).status_code == 200


@pytest.mark.parametrize("status,code,category", [
    (401, 190, "auth"), (403, 200, "auth"), (400, 10, "auth"), (400, 133010, "config"), (400, 130429, "rate_limit"),
    (400, 131056, "rate_limit"), (400, 131047, "window"), (400, 131026, "recipient"), (400, 131030, "recipient"),
    (500, 131000, "server"), (503, None, "server"), (429, None, "rate_limit"), (400, 100, "invalid"),
    (400, "garbage", "invalid")])
def test_graph_error_classification(status, code, category):
    assert notify.classify_graph_error(status, code) == category


def test_uncertain_send_is_recorded_and_never_resent(wa_live, http):
    http.behaviour = "read_timeout"
    phone = fake_phone()
    assert _send_one(phone) is False
    (m,) = out_messages(phone)
    assert m.status == "UNCERTAIN" and m.error_code == "UNCERTAIN" and "_retry_to" not in m.payload
    http.behaviour = "ok"
    n = len(http.calls)
    _retry_sweep()
    assert len(http.calls) == n  # not re-sent: Meta may already have delivered it


def test_expired_token_fails_fast_and_raises_one_ops_alert(wa_live, http):
    http.behaviour = "http190"
    for _ in range(3):
        _send_one(fake_phone())
    _retry_sweep()
    assert len(http.calls) == 3  # auth failures are not retried
    (alert,) = _reviews("WHATSAPP_UNAVAILABLE")
    assert alert.severity == "HIGH" and alert.detail["error_code"] == "190" and alert.detail["category"] == "auth"
    assert "FAKE_token_not_real" not in json.dumps(alert.detail) + alert.title


def test_closed_customer_service_window_is_recorded_not_retried(wa_live, http):
    http.behaviour = "http131047"
    phone = fake_phone()
    _send_one(phone)
    (m,) = out_messages(phone)
    assert m.status == "FAILED" and m.error_code == "131047" and "_retry_to" not in m.payload


def test_pair_rate_limit_is_retried(wa_live, http):
    http.behaviour = "http131056"
    phone = fake_phone()
    _send_one(phone)
    assert "_retry_to" in out_messages(phone)[0].payload


def test_processing_error_is_retried_with_backoff_then_succeeds(client, wa_inbound, monkeypatch):
    from weza.api.v1 import public
    real, calls = public.inbound, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return real(*a, **k)
    monkeypatch.setattr(public, "inbound", flaky)
    phone = fake_phone()
    text_msg(client, phone, "I need 5 million for stock for my shop")
    (row,) = inbox_rows(phone)
    assert row.status == "PENDING" and row.attempts == 1 and row.next_attempt_at is not None
    assert row.reason == "RETRY:RuntimeError"
    _inbox_retry(minutes=0)  # backoff not elapsed
    assert inbox_rows(phone)[0].status == "PENDING" and journeys_for(phone) == []
    _inbox_retry(minutes=1)
    assert inbox_rows(phone)[0].status == "DONE" and len(journeys_for(phone)) == 1 and out_messages(phone)


def test_poison_message_gives_up_apologises_escalates_and_unblocks_the_number(client, wa_inbound, monkeypatch):
    from weza.api.v1 import public
    real = public.inbound
    phone = fake_phone()

    def boom(*a, **k):
        raise RuntimeError("always")
    monkeypatch.setattr(public, "inbound", boom)
    text_msg(client, phone, "I need 5 million for stock for my shop", mid=f"wamid.FAKE_poison_{phone}")
    text_msg(client, phone, "second message waits behind the first", mid=f"wamid.FAKE_after_{phone}")
    assert [r.status for r in inbox_rows(phone)] == ["PENDING", "PENDING"]  # order kept: second waits
    _inbox_retry(minutes=1)

    def poison_only(*a, **k):
        return boom() if k.get("message_id", "").startswith("wamid.FAKE_poison") else real(*a, **k)
    monkeypatch.setattr(public, "inbound", poison_only)
    _inbox_retry(minutes=5)
    first, second = inbox_rows(phone)
    assert (first.status, first.reason, first.attempts) == ("FAILED", "PROCESSING_ERROR", 3)
    assert first.payload_enc is None  # content wiped even on failure
    assert second.status == "DONE" and len(journeys_for(phone)) == 1  # the number is not blocked
    assert any(m.body == wa_in.PROCESSING_FAILED_REPLY for m in out_messages(phone))
    assert any(r.object_id == str(first.id) for r in _reviews("WHATSAPP_INBOUND_FAILED"))


def test_failure_after_a_reply_was_sent_is_not_retried(client, wa_live, http, monkeypatch):
    """If WEZA already submitted a reply to Meta, retrying would send the customer a duplicate."""
    from weza.api.v1 import public

    def send_then_crash(db, phone, **k):
        notify.send_customer_message(db, phone, "partial reply", channel="whatsapp")
        raise RuntimeError("after send")
    monkeypatch.setattr(public, "inbound", send_then_crash)
    phone = fake_phone()
    text_msg(client, phone, "I need 5 million for stock for my shop")
    (row,) = inbox_rows(phone)
    assert (row.status, row.reason) == ("FAILED", "PARTIAL_REPLY")
    assert len(http.calls) == 1  # the partial reply only: no apology, no retry
    _inbox_retry(minutes=10)
    assert len(http.calls) == 1


def test_message_whose_queue_event_was_lost_is_picked_up_by_the_sweep(client, wa_inbound):
    from weza.platform.models import EventDelivery, OutboxEvent
    phone = fake_phone()
    text_msg(client, phone, "I need 5 million for stock for my shop", process=False)
    (row,) = inbox_rows(phone)
    with session_scope() as db:
        ev_ids = select(OutboxEvent.id).where(OutboxEvent.aggregate_id == str(row.id))
        for d in db.execute(select(EventDelivery).where(EventDelivery.event_id.in_(ev_ids))).scalars():
            d.status = "DEAD"
    drain()
    assert inbox_rows(phone)[0].status == "PENDING"
    _inbox_retry(minutes=0)  # too fresh: the normal path may still be on its way
    assert inbox_rows(phone)[0].status == "PENDING"
    _inbox_retry(minutes=3)
    assert inbox_rows(phone)[0].status == "DONE" and len(journeys_for(phone)) == 1


def test_too_long_message_gets_an_explanation(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "I need money for school fees.")
    text_msg(client, phone, "x" * 2500)
    assert inbox_rows(phone)[-1].status == "DROPPED"
    assert out_messages(phone)[-1].body == "Message is too long."


def test_app_secret_format_warning_names_only(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_app_secret", "short-secret")
    assert s.channel_config_summary()["warnings"] == ["WHATSAPP_APP_SECRET_FORMAT"]
    assert "short-secret" not in json.dumps(s.channel_config_summary())
    monkeypatch.setattr(s, "whatsapp_app_secret", "0123456789abcdef0123456789ABCDEF")
    assert s.channel_config_summary()["warnings"] == []


# ------------------------------------------------------------------ read-only account check script


class FakeGraph:
    def __init__(self, token_ok=True, coexistence=True):
        self.token_ok, self.coexistence, self.urls = token_ok, coexistence, []

    def __call__(self, url, params=None, timeout=None, **kw):
        self.urls.append(url)
        req = httpx.Request("GET", url)
        if not self.token_ok:
            return httpx.Response(400, json={"error": {"code": 190, "error_subcode": 463, "type": "OAuthException",
                                                       "message": "Session has expired"}}, request=req)
        path = url.split("/", 4)[-1]
        if path == "debug_token":
            data = {"data": {"is_valid": True, "type": "SYSTEM_USER", "app_id": "111", "expires_at": 0,
                             "scopes": ["whatsapp_business_messaging", "whatsapp_business_management"]}}
        elif path == "me":
            data = {"id": "1"}
        elif path == "000000000000000":
            data = {"display_phone_number": "+256 700 000 123", "verified_name": "Weza", "platform_type": "CLOUD_API",
                    "is_on_biz_app": self.coexistence, "code_verification_status": "VERIFIED"}
        elif path == "111/subscriptions":
            data = {"data": [{"object": "whatsapp_business_account", "callback_url": "https://x/webhook",
                              "active": True, "fields": [{"name": "messages", "version": "v25.0"}]}]}
        else:
            data = {"data": []}
        return httpx.Response(200, json=data, request=req)


def _account_check(monkeypatch, http_fake, **settings):
    from scripts import whatsapp_account_check as chk
    s = get_settings()
    vals = {"whatsapp_token": "FAKE_SECRET_TOKEN_must_not_print", "whatsapp_phone_number_id": "000000000000000",
            "whatsapp_app_secret": "FAKE_APP_SECRET_must_not_print", "whatsapp_business_number": "256700000123",
            "whatsapp_business_account_id": "222", **settings}
    for k, v in vals.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(httpx, "get", http_fake)
    lines: list[str] = []
    return chk.check(s, out=lines.append), "\n".join(lines)


def test_account_check_reports_coexistence_without_leaking_secrets(monkeypatch):
    g = FakeGraph()
    f, out = _account_check(monkeypatch, g)
    assert "Coexistence is active" in out
    assert f["phone_number"]["matches_WHATSAPP_BUSINESS_NUMBER"] is True
    assert f["webhook"][0]["fields"] == ["messages"]
    assert "FAKE_SECRET_TOKEN" not in out and "FAKE_APP_SECRET" not in out and "700000123" not in out
    assert all(u.startswith("https://graph.facebook.com/") for u in g.urls)  # GET only (httpx.post refuses)


def test_account_check_explains_an_expired_token(monkeypatch):
    f, out = _account_check(monkeypatch, FakeGraph(token_ok=False))
    assert f["token"]["_error"]["code"] == 190 and "System User token" in out
    assert "FAKE_SECRET_TOKEN" not in out


# ------------------------------------------------------------------ coexistence: account_update (disconnection)


def _account_update(event: str, *, waba="222", at=1739212624, phone="15550783881", info=None) -> dict:
    value = {"phone_number": phone, "event": event}
    if info is not None:
        value["disconnection_info"] = info
    return {"object": "whatsapp_business_account",
            "entry": [{"id": waba, "time": at, "changes": [{"field": "account_update", "value": value}]}]}


def _disconnect_alerts() -> list:
    return _reviews("WHATSAPP_DISCONNECTED")


def test_number_disconnected_in_the_app_raises_one_ops_alert(client, wa_inbound, monkeypatch, caplog):
    monkeypatch.setattr(wa_inbound, "whatsapp_business_account_id", "222")
    before = len(_disconnect_alerts())
    p = _account_update("PARTNER_REMOVED", at=1739212625,
                        info={"reason": "PRIMARY_INACTIVITY", "initiated_by": "SYSTEM"})
    with caplog.at_level(logging.DEBUG):
        for _ in range(2):  # Meta retry of the same webhook: still one alert
            assert send(client, p).status_code == 200
    alerts = _disconnect_alerts()
    assert len(alerts) == before + 1
    new = next(a for a in alerts if a.dedupe_key.endswith(":1739212625"))
    assert new.severity == "HIGH" and new.detail == {"event": "PARTNER_REMOVED", "reason": "PRIMARY_INACTIVITY",
                                                      "initiated_by": "SYSTEM"}
    blob = new.title + json.dumps(new.detail) + " ".join(str(getattr(r, "data", "")) for r in caplog.records)
    assert "15550783881" not in blob and "0783881" not in blob


def test_offboarded_alerts_and_reconnected_only_logs(client, wa_inbound, monkeypatch):
    monkeypatch.setattr(wa_inbound, "whatsapp_business_account_id", "222")
    before = len(_disconnect_alerts())
    assert send(client, _account_update("ACCOUNT_OFFBOARDED", at=1768477204)).status_code == 200
    assert send(client, _account_update("ACCOUNT_RECONNECTED", at=1768477205)).status_code == 200
    assert send(client, _account_update("PARTNER_ADDED", at=1768477206)).status_code == 200
    events = [a.detail["event"] for a in _disconnect_alerts()
              if a.dedupe_key.rsplit(":", 1)[-1] in ("1768477204", "1768477205", "1768477206")]
    assert events == ["ACCOUNT_OFFBOARDED"] and len(_disconnect_alerts()) == before + 1


def test_account_update_for_another_waba_is_ignored(client, wa_inbound, monkeypatch):
    monkeypatch.setattr(wa_inbound, "whatsapp_business_account_id", "222")
    before = len(_disconnect_alerts())
    assert send(client, _account_update("PARTNER_REMOVED", waba="999", at=1768477300)).status_code == 200
    assert len(_disconnect_alerts()) == before


def test_account_update_with_odd_values_is_acknowledged(client, wa_inbound):
    p = _account_update("X" * 500, at="not-a-number", info={"reason": ["bad"], "initiated_by": None})
    assert send(client, p).status_code == 200
    p = _account_update("PARTNER_REMOVED", at=1768477400, info="bad")
    assert send(client, p).status_code == 200


# ------------------------------------------------------------------ concurrency: webhook must never freeze the API


def test_webhook_waiting_for_a_row_lock_does_not_freeze_the_api(app, client, wa_live):
    """Regression (2026-10-16, live): two receipts for one message arrived together; the second waited for the first's
    row lock ON the event loop, so the first could never commit and the whole API hung. The wait must happen in a
    worker thread while the API keeps answering."""
    import asyncio
    import threading

    from weza.platform.db import SessionLocal
    phone = fake_phone()
    (m, *_) = _live_conversation(client, phone)
    holder = SessionLocal()  # plays the part of the first receipt's still-open transaction
    holder.execute(select(ChannelMessage).where(ChannelMessage.provider_message_id == m.provider_message_id)
                   .with_for_update()).scalars().first()
    raw = json.dumps(rw.status_payload(m.provider_message_id, "delivered", phone)).encode()
    # If the loop is blocked (the bug), asyncio timeouts can't fire: release the lock anyway so the test fails, not hangs.
    safety = threading.Timer(8, holder.commit)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            hook = asyncio.create_task(ac.post(URL, content=raw, headers={
                "Content-Type": "application/json", "X-Hub-Signature-256": rw.sign(raw)}))
            await asyncio.sleep(0.5)
            health = await asyncio.wait_for(ac.get("/api/v1/health"), timeout=5)
            assert health.status_code == 200 and not hook.done()  # the API answers while the receipt waits
            safety.cancel()
            holder.commit()  # first transaction finishes → the receipt proceeds
            assert (await asyncio.wait_for(hook, timeout=10)).status_code == 200

    safety.start()
    try:
        asyncio.run(scenario())
    finally:
        safety.cancel()
        holder.rollback()
        holder.close()
    got = next(x for x in out_messages(phone) if x.provider_message_id == m.provider_message_id)
    assert got.provider_status == "delivered"
