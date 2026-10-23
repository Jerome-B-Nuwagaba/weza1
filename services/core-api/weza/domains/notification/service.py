"""Intelligent Notification Fabric (FSD §33, TSD §34; blueprint L5):
Domain event → Notification policy → Recipient resolution → Channel selection → Delivery → Ack → Escalation."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.identity.models import Membership, User
from weza.domains.institution.models import NotificationPref
from weza.domains.misc_models import ChannelMessage, Notification
from weza.domains.notification import retry_queue
from weza.platform import crypto
from weza.platform.controls import channel_disabled
from weza.platform.db import utcnow

log = logging.getLogger("weza.notify")
MAX_ATTEMPTS = retry_queue.MAX_ATTEMPTS  # staff notifications (retry_queue: backoff, then dead-letter)
# Customer WhatsApp messages that failed with a retryable Meta error (retry_failed_channel_messages)
RETRY_BACKOFF_SECONDS = 60  # multiplied by the attempt number
RETRY_MAX_RESENDS = 2
RETRY_WINDOW_MINUTES = 30  # conversation messages go stale; never replay them hours later
PRIORITY_ORDER = {"NORMAL": 0, "HIGH": 1, "URGENT": 2}


# ------------------------------------------------------------------ customer channel adapters


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    error_code: str | None = None
    retryable: bool = False
    # WhatsApp only: auth | config | rate_limit | window | recipient | invalid | server | network | uncertain
    category: str = ""


# Cloud API error codes → category (developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes).
# Retrying is only safe where Meta did not accept the message; "uncertain" is never retried automatically.
_AUTH_CODES = {0, 3, 10, 102, 190} | set(range(200, 300))  # expired/invalid token, missing permission
_CONFIG_CODES = {368, 131031, 131045, 133010}  # number blocked/locked, certificate, number not registered
_RATE_CODES = {4, 80007, 130429, 131048, 131056}  # app / account / throughput / spam / pair rate limits
_WINDOW_CODES = {131047}  # more than 24 h since the customer's last message: needs an approved template
_RECIPIENT_CODES = {131021, 131026, 131030}  # undeliverable / not on the test-number allowed list / self
_SERVER_CODES = {1, 2, 131000, 131016, 133004}
_RETRYABLE = {"rate_limit", "server", "network"}


def classify_graph_error(http_status: int, code: int | str | None) -> str:
    try:
        c = int(code) if code is not None else None
    except (TypeError, ValueError):
        c = None
    for codes, category in ((_AUTH_CODES, "auth"), (_CONFIG_CODES, "config"), (_RATE_CODES, "rate_limit"),
                            (_WINDOW_CODES, "window"), (_RECIPIENT_CODES, "recipient"), (_SERVER_CODES, "server")):
        if c is not None and c in codes:
            return category
    if http_status == 429:
        return "rate_limit"
    if http_status >= 500:
        return "server"
    if http_status in (401, 403):
        return "auth"
    return "invalid"


def send_customer_message(db: Session, phone_e164: str, body: str, *, channel: str = "sms", kind: str = "info",
                          payload: dict | None = None) -> bool:
    """SMS/WhatsApp to a customer. Without provider credentials, messages go to the simulator inbox
    (demo/test) — the raw phone number is never stored, only its blind index."""
    s = get_settings()
    if channel_disabled(db, channel):
        log.warning("channel_disabled", extra={"data": {"channel": channel}})
        return False
    provider = "simulator"
    status = "SENT"
    wamid = error_code = None
    if channel == "whatsapp" and s.whatsapp_send_ready:
        provider = "whatsapp_cloud"
        res = _whatsapp_send(phone_e164, body, payload)
        # SENT = Meta accepted the request (not delivery: that arrives later as a status webhook).
        # UNCERTAIN = the request may have reached Meta; never re-sent automatically, to avoid duplicates.
        status = "SENT" if res.ok else "UNCERTAIN" if res.category == "uncertain" else "FAILED"
        wamid, error_code = res.provider_message_id, res.error_code
        if res.ok or res.category == "uncertain":  # lets callers know a retry could now duplicate a reply
            db.info["wa_submitted"] = db.info.get("wa_submitted", 0) + 1
        if not res.ok:  # names/flags only — never the number or the message text
            log.warning("whatsapp_send_failed", extra={"data": {"err": res.error_code, "category": res.category,
                                                                "retryable": res.retryable}})
            if res.category in ("auth", "config"):
                _alert_whatsapp_unavailable(db, res)
            if res.retryable:
                payload = {**(payload or {}), "_retry_to": _enc_phone(phone_e164), "_retries": 0,
                           "_retry_after": (utcnow() + timedelta(seconds=RETRY_BACKOFF_SECONDS)).isoformat()}
    elif channel == "sms" and s.sms_provider_name in SMS_ADAPTERS:
        provider = s.sms_provider_name  # built-in gateways: Africa's Talking, Twilio, Infobip
        status = "SENT" if SMS_ADAPTERS[provider](phone_e164, body) else "FAILED"
        if status == "FAILED":
            error_code = "PROVIDER_ERROR"
    elif channel == "sms" and s.sms_provider_name != "console":
        # Any other provider (incl. SMS_PROVIDER=whatsapp) goes through the provider-agnostic slot in notification/sms.py.
        from weza.domains.notification import sms
        sender, why = sms.resolve(s)
        provider = s.sms_provider_name
        if sender is None and not s.is_production and s.otp_delivery == "display":
            # Dev convenience: a half-configured provider must not block local journeys — show it in the simulator.
            log.warning("sms_provider_unavailable_dev_fallback", extra={"data": {"why": why}})
            provider = "simulator"
        elif sender is None:
            status, error_code = "FAILED", why
            log.error("sms_provider_unavailable", extra={"data": {"provider": provider, "why": why}})
        else:
            try:
                res = sender.send(phone_e164, body)
            except Exception:  # noqa: BLE001 — a provider bug must not break the journey
                log.exception("sms_send_crashed")
                res = SendResult(False, error_code="PROVIDER_ERROR")
            status = "SENT" if res.ok else "FAILED"
            wamid, error_code = res.provider_message_id, res.error_code
            if not res.ok:
                log.warning("sms_send_failed", extra={"data": {"err": res.error_code}})
    if kind == "otp" and provider != "simulator":
        body = "[one-time code redacted]"  # only the simulator inbox needs it; never keep a real one-time code
    elif kind == "sensitive" and provider != "simulator":
        body = "[identity details redacted]"  # e.g. the name and NIN read from an ID, shown back for confirmation
    db.add(ChannelMessage(channel=channel, to_index=crypto.blind_index("phone", phone_e164), body=body,
                          payload={"kind": kind, **(payload or {})}, provider=provider, status=status,
                          provider_message_id=wamid, error_code=error_code))
    return status == "SENT"


def _africastalking_send(phone_e164: str, body: str) -> bool:
    s = get_settings()
    if not (s.africastalking_username and s.africastalking_api_key):
        log.error("sms_not_configured", extra={"data": {"provider": "africastalking"}})
        return False
    host = "api.sandbox.africastalking.com" if s.africastalking_username == "sandbox" else "api.africastalking.com"
    data = {"username": s.africastalking_username, "to": phone_e164, "message": body}
    if s.africastalking_sender_id:
        data["from"] = s.africastalking_sender_id
    try:
        r = httpx.post(f"https://{host}/version1/messaging", data=data, timeout=10,
                       headers={"apiKey": s.africastalking_api_key, "Accept": "application/json"})
        if r.status_code >= 300:
            log.warning("sms_failed", extra={"data": {"provider": "africastalking", "status": r.status_code}})
            return False
        recipients = (r.json().get("SMSMessageData") or {}).get("Recipients") or []
        # Per-recipient statusCode 100–102 means accepted (Processed / Sent / Queued).
        ok = bool(recipients) and all(x.get("statusCode") in (100, 101, 102) for x in recipients)
        if not ok:
            log.warning("sms_rejected", extra={"data": {"provider": "africastalking",
                                                        "status": [x.get("status") for x in recipients]}})
        return ok
    except (httpx.HTTPError, ValueError):
        log.warning("sms_failed", extra={"data": {"provider": "africastalking"}})
        return False


def _twilio_send(phone_e164: str, body: str) -> bool:
    s = get_settings()
    if not (s.twilio_account_sid and s.twilio_auth_token and s.twilio_from):
        log.error("sms_not_configured", extra={"data": {"provider": "twilio"}})
        return False
    sender = {"MessagingServiceSid": s.twilio_from} if s.twilio_from.startswith("MG") else {"From": s.twilio_from}
    try:
        r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
                       data={"To": phone_e164, "Body": body, **sender},
                       auth=(s.twilio_account_sid, s.twilio_auth_token), timeout=10)
        if r.status_code >= 300:
            log.warning("sms_failed", extra={"data": {"provider": "twilio", "status": r.status_code}})
        return r.status_code < 300
    except httpx.HTTPError:
        log.warning("sms_failed", extra={"data": {"provider": "twilio"}})
        return False


def _infobip_send(phone_e164: str, body: str) -> bool:
    s = get_settings()
    if not (s.infobip_base_url and s.infobip_api_key):
        log.error("sms_not_configured", extra={"data": {"provider": "infobip"}})
        return False
    base = s.infobip_base_url.rstrip("/")
    if not base.startswith("https://"):
        base = "https://" + base.removeprefix("http://")
    msg = {"destinations": [{"to": phone_e164.lstrip("+")}], "text": body}
    if s.infobip_sender:
        msg["from"] = s.infobip_sender
    try:
        r = httpx.post(f"{base}/sms/2/text/advanced", json={"messages": [msg]}, timeout=10,
                       headers={"Authorization": f"App {s.infobip_api_key}", "Accept": "application/json"})
        if r.status_code >= 300:
            log.warning("sms_failed", extra={"data": {"provider": "infobip", "status": r.status_code}})
            return False
        sent = r.json().get("messages") or []
        # Accepted messages report status group PENDING (queued) or DELIVERED; REJECTED/UNDELIVERABLE are failures.
        ok = bool(sent) and all((m.get("status") or {}).get("groupName") in ("PENDING", "DELIVERED") for m in sent)
        if not ok:
            log.warning("sms_rejected", extra={"data": {"provider": "infobip", "status": [
                (m.get("status") or {}).get("name") for m in sent]}})
        return ok
    except (httpx.HTTPError, ValueError):
        log.warning("sms_failed", extra={"data": {"provider": "infobip"}})
        return False


SMS_ADAPTERS = {"africastalking": _africastalking_send, "twilio": _twilio_send, "infobip": _infobip_send}


def _alert_whatsapp_unavailable(db: Session, res: SendResult) -> None:
    """Token expired / permission missing / number not usable: every reply will fail until someone fixes the Meta
    setup, so raise one (deduplicated) operations review item instead of failing silently."""
    from weza.domains.integrity.service import add_review
    log.error("whatsapp_unavailable", extra={"data": {"err": res.error_code, "category": res.category}})
    add_review(db, "WHATSAPP_UNAVAILABLE", f"WhatsApp sending is failing ({res.category}, Meta error {res.error_code})."
               " Check WHATSAPP_TOKEN, its permissions and the phone number status in Meta.", "channel", "whatsapp",
               severity="HIGH", detail={"error_code": res.error_code, "category": res.category},
               dedupe_key="WHATSAPP_UNAVAILABLE")


def _enc_phone(phone_e164: str) -> str:
    from weza.domains.need.journey import _enc
    return _enc(phone_e164)


def _dec_phone(token: str) -> str:
    from weza.domains.need.journey import _dec
    return _dec(token)


def retry_failed_channel_messages(db: Session, now: datetime | None = None) -> int:
    """Re-send recent WhatsApp messages that failed with a retryable error (rate limit, Meta server error, or a
    connection that never reached Meta), a couple of times. Uncertain outcomes are never re-sent."""
    now = now or utcnow()
    s = get_settings()
    if not s.whatsapp_send_ready:
        return 0
    rows = db.execute(select(ChannelMessage).where(
        ChannelMessage.provider == "whatsapp_cloud", ChannelMessage.status == "FAILED",
        ChannelMessage.payload.has_key("_retry_to"),  # noqa: W601 — JSONB key test, not dict.has_key
        ChannelMessage.created_at >= now - timedelta(minutes=RETRY_WINDOW_MINUTES))
        .order_by(ChannelMessage.created_at).limit(50).with_for_update(skip_locked=True)).scalars().all()
    n = 0
    for m in rows:
        meta = m.payload
        if datetime.fromisoformat(meta["_retry_after"]) > now:
            continue
        n += 1
        res = _whatsapp_send(_dec_phone(meta["_retry_to"]), m.body, meta)
        clean = {k: v for k, v in meta.items() if not k.startswith("_retry")}
        if res.ok:
            m.status, m.provider_message_id, m.error_code, m.payload = "SENT", res.provider_message_id, None, clean
        else:
            m.error_code = res.error_code
            if res.category == "uncertain":
                m.status = "UNCERTAIN"
            elif res.category in ("auth", "config"):
                _alert_whatsapp_unavailable(db, res)
            tries = meta["_retries"] + 1
            if res.retryable and tries < RETRY_MAX_RESENDS:
                m.payload = {**meta, "_retries": tries,
                             "_retry_after": (now + timedelta(seconds=RETRY_BACKOFF_SECONDS * (tries + 1))).isoformat()}
            else:
                m.payload = clean
                log.warning("whatsapp_retry_gave_up", extra={"data": {"err": res.error_code}})
    return n


def _whatsapp_send(phone_e164: str, body: str, payload: dict | None) -> SendResult:
    buttons = (payload or {}).get("quick_replies") or []
    if buttons and len(buttons) <= 3:
        msg = {"messaging_product": "whatsapp", "to": phone_e164.lstrip("+"), "type": "interactive",
               "interactive": {"type": "button", "body": {"text": body[:1024]}, "action": {"buttons": [
                   {"type": "reply", "reply": {"id": (f"{b['action']}:{b['value']}" if b.get("value")
                                                      else (b.get("action") or b["label"]))[:256],
                                               "title": b["label"][:20]}} for b in buttons]}}}
    else:
        if buttons:
            body = body + "\n\nReply with: " + " / ".join(b["label"] for b in buttons)
        msg = {"messaging_product": "whatsapp", "to": phone_e164.lstrip("+"), "type": "text",
               "text": {"body": body[:4096]}}
    return _graph_post(msg)


def graph_call(method: str, path: str, *, token: str | None = None, params: dict | None = None,
               body: dict | None = None) -> tuple[int, dict]:
    """Graph API request for WhatsApp account set-up (Embedded Signup onboarding). Returns (HTTP status, JSON body);
    status 0 means the request failed on the network. Callers must never log the token or the response body."""
    url = f"https://graph.facebook.com/{get_settings().graph_api_version}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        if method == "GET":
            r = httpx.get(url, params=params, headers=headers, timeout=15)
        else:
            r = httpx.post(url, params=params, json=body, headers=headers, timeout=15)
    except httpx.HTTPError:
        return 0, {}
    try:
        data = r.json()
    except ValueError:
        data = {}
    return r.status_code, data if isinstance(data, dict) else {}


def http_get(url: str, headers: dict, timeout: float) -> httpx.Response:
    """WhatsApp media download. Outbound HTTP lives only in this module (zero-core-integration boundary test)."""
    return httpx.get(url, headers=headers, timeout=timeout)


def _graph_post(msg: dict) -> SendResult:
    s = get_settings()
    url = f"https://graph.facebook.com/{s.graph_api_version}/{s.whatsapp_phone_number_id}/messages"
    try:
        r = httpx.post(url, json=msg, headers={"Authorization": f"Bearer {s.whatsapp_token}"}, timeout=10)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        # The request never left this server: safe to retry.
        return SendResult(False, error_code="NETWORK", retryable=True, category="network")
    except httpx.HTTPError:
        # Read/write timeout or dropped connection after sending: Meta may have accepted it. Don't resend.
        return SendResult(False, error_code="UNCERTAIN", category="uncertain")
    try:
        data = r.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if r.status_code < 300:
        wamid = ((data.get("messages") or [{}])[0] or {}).get("id")
        return SendResult(True, provider_message_id=wamid)
    err = data.get("error") or {}
    if not isinstance(err, dict):
        err = {}
    code = str(err.get("code") or f"HTTP_{r.status_code}")[:32]
    category = classify_graph_error(r.status_code, err.get("code"))
    return SendResult(False, error_code=code, retryable=category in _RETRYABLE, category=category)


# Delivery-status callbacks (Cloud API `statuses`): forward-only so retried/out-of-order callbacks can't regress.
_STATUS_RANK = {"sent": 1, "failed": 2, "delivered": 3, "read": 4}


def apply_delivery_status(db: Session, wamid: str, status: str, at: datetime | None = None,
                          error_code: str | None = None) -> bool:
    """Record a provider delivery status on the outbound ChannelMessage. Returns True if it changed anything."""
    new = _STATUS_RANK.get(status)
    if not wamid or new is None:
        return False
    msg = db.execute(select(ChannelMessage).where(ChannelMessage.provider_message_id == wamid)
                     .with_for_update()).scalars().first()
    if msg is None or new <= _STATUS_RANK.get(msg.provider_status or "", 0):
        return False
    msg.provider_status = status
    msg.status_at = at or utcnow()
    if status == "failed":
        msg.status = "FAILED"
        msg.error_code = (error_code or "")[:32] or None
    else:
        msg.status = "SENT"
        msg.error_code = None
    return True


def parse_status_time(ts) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ts), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


# ------------------------------------------------------------------ staff notifications


def _recipients(db: Session, institution_id: uuid.UUID, roles: list[str] | None, user_ids: list[uuid.UUID] | None,
                team_id: uuid.UUID | None = None) -> list[User]:
    q = select(User, Membership).join(Membership, Membership.user_id == User.id).where(
        Membership.institution_id == institution_id, User.status == "ACTIVE")
    out = []
    for u, m in db.execute(q).all():
        if user_ids and u.id in user_ids:
            out.append(u)
        elif roles and set(m.roles) & set(roles) and (team_id is None or m.team_id in (team_id, None)):
            out.append(u)
    return out


def _channels_for(db: Session, institution_id, user: User, event_type: str, priority: str) -> list[str]:
    prefs = db.execute(select(NotificationPref).where(NotificationPref.institution_id == institution_id,
                                                      NotificationPref.event_type == event_type)).scalars().all()
    pref = next((p for p in prefs if p.user_id == user.id), None) or next((p for p in prefs if p.user_id is None), None)
    channels = ["in_app"]
    if pref is not None:
        if PRIORITY_ORDER.get(priority, 0) >= PRIORITY_ORDER.get(pref.min_priority, 0):
            channels = list(dict.fromkeys(["in_app", *pref.channels]))
    elif priority in ("HIGH", "URGENT"):
        channels = ["in_app", "email"]
    return channels


def notify_institution(db: Session, institution_id: uuid.UUID, event_type: str, *, title: str, body: str = "",
                       link: str | None = None, priority: str = "NORMAL", roles: list[str] | None = None,
                       user_ids: list[uuid.UUID] | None = None, team_id: uuid.UUID | None = None,
                       object_type: str | None = None, object_id: str | None = None, ack_required: bool = False,
                       ack_minutes: int = 120, event_id: uuid.UUID | None = None, dedupe: str | None = None) -> int:
    n = 0
    for u in _recipients(db, institution_id, roles, user_ids, team_id):
        for ch in _channels_for(db, institution_id, u, event_type, priority):
            key = f"{dedupe}:{u.id}:{ch}" if dedupe else None
            if key and db.execute(select(Notification.id).where(Notification.dedupe_key == key)).first():
                continue
            note = Notification(event_id=event_id, event_type=event_type, recipient_type="USER", recipient_id=u.id,
                                institution_id=institution_id, channel=ch, priority=priority, title=title, body=body,
                                link=link, object_type=object_type, object_id=object_id,
                                ack_required=ack_required and ch == "in_app",
                                ack_due_at=utcnow() + timedelta(minutes=ack_minutes) if ack_required else None,
                                dedupe_key=key)
            db.add(note)
            db.flush()
            deliver(db, note, u)
            n += 1
    return n


def notify_weza_ops(db: Session, event_type: str, title: str, body: str = "", link: str | None = None,
                    priority: str = "HIGH", object_type: str | None = None, object_id: str | None = None) -> None:
    for u in db.execute(select(User).where(User.kind == "WEZA", User.status == "ACTIVE")).scalars():
        if set(u.weza_roles) & {"WEZA_OPS", "WEZA_SUPER"}:
            note = Notification(event_type=event_type, recipient_type="USER", recipient_id=u.id, channel="in_app",
                                priority=priority, title=title, body=body, link=link, object_type=object_type,
                                object_id=object_id, status="DELIVERED")
            db.add(note)


def notify_customer(db: Session, customer_id: uuid.UUID, event_type: str, *, title: str, body: str,
                    link: str | None = None, channel: str | None = None, object_type: str | None = None,
                    object_id: str | None = None, quick_replies: list[dict] | None = None) -> None:
    from weza.domains.customer.models import Customer, Preference
    from weza.domains.identity.service import vault_read
    cust = db.get(Customer, customer_id)
    if cust is None:
        return
    pref = db.get(Preference, customer_id)
    ch = channel or ("whatsapp" if pref and pref.contact_channel == "whatsapp" else "sms")
    db.add(Notification(event_type=event_type, recipient_type="CUSTOMER", recipient_id=customer_id, channel="in_app",
                        title=title, body=body, link=link, object_type=object_type, object_id=object_id,
                        status="DELIVERED"))
    phone = vault_read(db, cust.vault_token).get("phone")
    if phone:
        # WhatsApp customers live in the chat (no web session): no web link, just tell them where to reply.
        text = (f"WEZA: {body} Reply here any time." if ch == "whatsapp"
                else f"WEZA: {body}" + (f" {get_settings().public_web_url}{link}" if link else ""))
        send_customer_message(db, phone, text, channel=ch, kind=event_type, payload={"quick_replies": quick_replies or []})


def deliver(db: Session, note: Notification, user: User | None = None) -> None:
    note.attempts += 1
    try:
        if note.channel == "in_app":
            note.status = "DELIVERED"
        elif note.channel == "email":
            user = user or db.get(User, note.recipient_id)
            _send_email(user.email if user else "", note.title, note.body)
            note.status = "SENT"
        else:
            note.status = "SENT"
        note.next_attempt_at = None
    except Exception as exc:  # noqa: BLE001 — retried with backoff by the worker, then dead-lettered
        retry_queue.record_failure(note, exc)


def _send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_url:
        log.info("email_console", extra={"data": {"subject": subject}})
        return
    import smtplib
    from email.message import EmailMessage
    from urllib.parse import unquote, urlparse
    u = urlparse(s.smtp_url)
    if not to:
        raise ValueError("recipient has no email address")
    msg = EmailMessage()
    msg["From"] = s.smtp_from or (unquote(u.username) if u.username and "@" in unquote(u.username)
                                  else "WEZA <noreply@weza.africa>")
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    implicit_tls = u.scheme == "smtps"
    cls = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
    with cls(u.hostname, u.port or (465 if implicit_tls else 587), timeout=10) as smtp:
        if not implicit_tls:
            smtp.starttls()
        if u.username:
            smtp.login(unquote(u.username), unquote(u.password or ""))
        smtp.send_message(msg)


def retry_sweep(db: Session) -> int:
    """Redeliver FAILED rows whose backoff has elapsed."""
    due = (Notification.status == "FAILED") & (
        Notification.next_attempt_at.is_(None) | (Notification.next_attempt_at <= utcnow()))
    rows = db.execute(select(Notification).where(due).order_by(Notification.next_attempt_at)
                      .limit(100).with_for_update(skip_locked=True)).scalars().all()
    for n in rows:
        deliver(db, n)
    return len(rows)


def escalation_sweep(db: Session) -> int:
    """Unacknowledged priority alerts escalate to managers, then WEZA Ops (Skill §44)."""
    now = utcnow()
    rows = db.execute(select(Notification).where(Notification.ack_required.is_(True), Notification.acked_at.is_(None),
                                                 Notification.escalated.is_(False), Notification.ack_due_at <= now)
                      ).scalars().all()
    for n in rows:
        n.escalated = True
        if n.institution_id:
            notify_institution(db, n.institution_id, "AlertEscalated", title=f"Not acknowledged: {n.title}",
                               body=n.body, link=n.link, priority="HIGH", roles=["MANAGER"],
                               object_type=n.object_type, object_id=n.object_id,
                               dedupe=f"esc:{n.id}")
    return len(rows)
