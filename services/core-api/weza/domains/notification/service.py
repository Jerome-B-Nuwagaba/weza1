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
from weza.platform import crypto
from weza.platform.controls import channel_disabled
from weza.platform.db import utcnow

log = logging.getLogger("weza.notify")
MAX_ATTEMPTS = 5
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
        status = "SENT" if res.ok else "FAILED"
        wamid, error_code = res.provider_message_id, res.error_code
        if not res.ok:  # names/flags only — never the number or the message text
            log.warning("whatsapp_send_failed", extra={"data": {"err": res.error_code, "retryable": res.retryable}})
            if res.retryable:
                payload = {**(payload or {}), "_retry_to": _enc_phone(phone_e164), "_retries": 0,
                           "_retry_after": (utcnow() + timedelta(seconds=RETRY_BACKOFF_SECONDS)).isoformat()}
    elif channel == "sms" and s.sms_provider_name != "console":
        # Real SMS goes through the provider-agnostic slot in notification/sms.py.
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
        body = "Verification code sent."  # never keep a real one-time code in the database
    db.add(ChannelMessage(channel=channel, to_index=crypto.blind_index("phone", phone_e164), body=body,
                          payload={"kind": kind, **(payload or {})}, provider=provider, status=status,
                          provider_message_id=wamid, error_code=error_code))
    return status == "SENT"


def _enc_phone(phone_e164: str) -> str:
    from weza.domains.need.journey import _enc
    return _enc(phone_e164)


def _dec_phone(token: str) -> str:
    from weza.domains.need.journey import _dec
    return _dec(token)


def retry_failed_channel_messages(db: Session, now: datetime | None = None) -> int:
    """Re-send recent WhatsApp messages that failed with a retryable error (429/5xx/network), a couple of times."""
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


def http_get(url: str, headers: dict, timeout: float) -> httpx.Response:
    """The only outbound GET in the codebase (zero-core-integration boundary test): WhatsApp media download."""
    return httpx.get(url, headers=headers, timeout=timeout)


def _graph_post(msg: dict) -> SendResult:
    s = get_settings()
    url = f"https://graph.facebook.com/{s.graph_api_version}/{s.whatsapp_phone_number_id}/messages"
    try:
        r = httpx.post(url, json=msg, headers={"Authorization": f"Bearer {s.whatsapp_token}"}, timeout=10)
    except httpx.HTTPError:
        return SendResult(False, error_code="NETWORK", retryable=True)
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
    code = str(err.get("code") or f"HTTP_{r.status_code}")[:32]
    return SendResult(False, error_code=code, retryable=r.status_code == 429 or r.status_code >= 500)


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
        text = f"WEZA: {body}" + (f" {get_settings().public_web_url}{link}" if link else "")
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
    except Exception as exc:  # noqa: BLE001 — retried by the worker, then dead-lettered
        note.status = "FAILED" if note.attempts < MAX_ATTEMPTS else "DEAD"
        note.last_error = str(exc)[:500]


def _send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_url:
        log.info("email_console", extra={"data": {"subject": subject}})
        return
    import smtplib
    from email.message import EmailMessage
    from urllib.parse import urlparse
    u = urlparse(s.smtp_url)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = u.username or "noreply@weza.africa", to, subject
    msg.set_content(body)
    with smtplib.SMTP(u.hostname, u.port or 587, timeout=10) as smtp:
        smtp.starttls()
        if u.username:
            smtp.login(u.username, u.password or "")
        smtp.send_message(msg)


def retry_sweep(db: Session) -> int:
    rows = db.execute(select(Notification).where(Notification.status == "FAILED").limit(100)).scalars().all()
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
