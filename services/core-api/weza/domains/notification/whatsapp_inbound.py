"""WhatsApp inbound pipeline: acknowledge fast, process durably.

The webhook only verifies the signature and calls `receive()`, which stores one inbox row per provider message id
(unique → Meta retries are harmless) and emits an outbox event. The worker consumer then runs `process_phone()`,
which handles that number's pending messages in arrival order through the normal `public.inbound()` seam.
Message content is kept encrypted only until processed, then wiped. Nothing here logs phone numbers or text.
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from weza.domains.misc_models import WhatsappInbox
from weza.domains.notification.service import send_customer_message
from weza.platform import crypto
from weza.platform.controls import rate_limit
from weza.platform.db import utcnow
from weza.platform.errors import RateLimited, WezaError
from weza.platform.events import emit

log = logging.getLogger("weza.whatsapp")

UNSUPPORTED_REPLY = ("Sorry, I can only read typed messages and button taps for now. "
                     "Please type your message or tap one of the options.")
# Message types we read as text/buttons; reactions and system notices need no reply; everything else is unsupported.
_IGNORED_TYPES = {"reaction", "system", "ephemeral", "request_welcome"}


def classify(msg: dict) -> dict:
    """Normalise a Cloud API message → {kind: message|unsupported|ignored, type, text, button_id, button_title}."""
    mtype = str(msg.get("type") or "unknown")[:24]
    out = {"type": mtype, "text": None, "button_id": None, "button_title": None}
    if mtype == "text":
        body = ((msg.get("text") or {}).get("body") or "")
        out.update(kind="message" if body.strip() else "ignored", text=body)
    elif mtype == "interactive":
        inter = msg.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        if reply.get("id"):
            out.update(kind="message", button_id=reply["id"], button_title=reply.get("title"))
        else:
            out["kind"] = "unsupported"
    elif mtype == "button":  # template quick-reply tap
        b = msg.get("button") or {}
        out.update(kind="message" if (b.get("text") or "").strip() else "ignored", text=b.get("text"))
    elif mtype in _IGNORED_TYPES:
        out["kind"] = "ignored"
    else:
        out["kind"] = "unsupported"  # image, audio, video, document, sticker, location, contacts, order, unknown
    return out


def receive(db: Session, msg: dict) -> WhatsappInbox | None:
    """Store a provider message once and queue it for processing. Returns None for duplicates/invalid input."""
    from weza.domains.intelligence.parsing import parse_phone
    from weza.domains.need.journey import _enc
    wamid = str(msg.get("id") or "")[:128]
    sender = str(msg.get("from") or "").lstrip("+")
    if not wamid or not sender:
        return None
    phone = parse_phone("+" + sender) or "+" + sender
    c = classify(msg)
    row = WhatsappInbox(provider_message_id=wamid, msg_type=c["type"], phone_index=crypto.blind_index("phone", phone),
                        payload_enc=_enc(json.dumps({"phone": phone, **c})))
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return None  # already received: Meta retry
    emit(db, "WhatsAppInboundReceived", topic="customer", aggregate_type="whatsapp_inbox", aggregate_id=row.id)
    return row


def process_phone(db: Session, phone_index: str) -> int:
    """Process every pending message for one number, oldest first (row locks keep concurrent workers in order)."""
    rows = db.execute(select(WhatsappInbox).where(WhatsappInbox.phone_index == phone_index,
                                                  WhatsappInbox.status == "PENDING")
                      .order_by(WhatsappInbox.received_at, WhatsappInbox.id).with_for_update()).scalars().all()
    for row in rows:
        _process_one(db, row)
    return len(rows)


def _finish(row: WhatsappInbox, status: str, reason: str | None = None) -> None:
    row.status, row.reason, row.payload_enc, row.processed_at = status, reason, None, utcnow()


def _process_one(db: Session, row: WhatsappInbox) -> None:
    from weza.api.v1 import public
    from weza.domains.need.journey import _dec
    data = json.loads(_dec(row.payload_enc))
    phone, kind = data["phone"], data["kind"]
    if kind == "ignored":
        return _finish(row, "IGNORED")
    if kind == "unsupported":
        try:  # at most a few "can't read that" replies per number, so media floods don't become reply floods
            rate_limit(db, f"wa:unsup:{row.phone_index}", 3, 600)
            send_customer_message(db, phone, UNSUPPORTED_REPLY, channel="whatsapp", kind="unsupported_type")
        except RateLimited:
            pass
        return _finish(row, "DONE", "UNSUPPORTED_TYPE")
    try:
        with db.begin_nested():
            public.inbound(db, phone, text=data["text"], button_id=data["button_id"],
                           button_title=data["button_title"], message_id=row.provider_message_id)
    except WezaError as exc:  # rate limited / invalid message: permanent for this message → acknowledge, don't retry
        log.info("whatsapp_inbound_dropped", extra={"data": {"reason": exc.code}})
        return _finish(row, "DROPPED", str(exc.code)[:40])
    _finish(row, "DONE")
