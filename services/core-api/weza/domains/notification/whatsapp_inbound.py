"""WhatsApp inbound pipeline: acknowledge fast, process durably.

The webhook only verifies the signature and calls `receive()`, which stores one inbox row per provider message id
(unique → Meta retries are harmless) and emits an outbox event. The worker consumer then runs `process_phone()`,
which handles that number's pending messages in arrival order through the normal `public.inbound()` seam.
Message content is kept encrypted only until processed, then wiped. Nothing here logs phone numbers or text.
"""

import json
import logging

import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from weza.domains.customer import documents as docs
from weza.domains.misc_models import WhatsappInbox
from weza.domains.notification import whatsapp_media
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
    out = {"type": mtype, "text": None, "button_id": None, "button_title": None, "media_id": None, "mime": None,
           "filename": None, "caption": None}
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
    elif mtype in ("image", "document"):  # customer documents: downloaded and stored by the document pipeline
        m = msg.get(mtype) or {}
        if m.get("id"):
            out.update(kind="media", media_id=str(m["id"])[:200], mime=m.get("mime_type"),
                       filename=m.get("filename"), caption=m.get("caption"))
        else:
            out["kind"] = "unsupported"
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
    if kind == "media":
        return _process_media(db, row, data)
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


# ------------------------------------------------------------------ customer documents (photos / PDFs)

VERIFY_FIRST = "Thanks. Please finish verifying your phone number first, then send the document again."
NEED_JOURNEY = ("Please tell me what financing you need first (for example: I need UGX 5 million for stock). "
                "Then you can send your documents here.")
DOWNLOAD_FAILED = "Sorry, I couldn't download that file. Please send it again."
TOO_LARGE = "That file is larger than 10 MB. Please send a smaller photo or PDF."

# caption / filename hints → document type (first match wins); otherwise the first document still outstanding
_HINTS = [
    (r"\bpay ?slip|salary", "payslip"), (r"mobile ?money|momo|airtel|\bmtn\b", "mobile_money_statement"),
    (r"bank|statement", "bank_statement"), (r"\bnin\b|national|\bid\b|identity|passport", "national_id"),
    (r"registration|certificate|ursb|\btin\b", "business_registration"), (r"licen[cs]e|trading", "trading_licence"),
    (r"employment|appointment|letter", "employment_letter"), (r"\bfarm|\bland\b|title", "farm_records"),
]


def guess_doc_type(caption: str | None, filename: str | None, outstanding: list[str]) -> str:
    text = f"{caption or ''} {filename or ''}".lower()
    for pattern, doc_type in _HINTS:
        if re.search(pattern, text):
            return doc_type
    return outstanding[0] if outstanding else "other"


def _active_journey(db: Session, phone_index: str):
    from weza.platform.models import GraphInstance
    return db.execute(select(GraphInstance).where(
        GraphInstance.graph_type == "customer_journey", GraphInstance.status.in_(["WAITING", "RUNNING"]),
        GraphInstance.state["wa_index"].astext == phone_index).order_by(GraphInstance.updated_at.desc()).limit(1)
    ).scalar_one_or_none()


def _outstanding_doc_types(db: Session, need_id: uuid.UUID, customer_id: uuid.UUID) -> list[str]:
    from weza.domains.customer.models import Document
    from weza.domains.matching.models import Match
    have = set(db.execute(select(Document.doc_type).where(Document.customer_id == customer_id,
                                                          Document.pipeline_state == "STORED")).scalars())
    out: list[str] = []
    for m in db.execute(select(Match).where(Match.need_id == need_id, Match.state.in_(["RANKED", "PRESENTED"]),
                                            Match.readiness == "ALMOST")).scalars():
        for o in (m.explanation or {}).get("outstanding", []):
            t = o.get("doc_type")
            if t and t not in have and t not in out:
                out.append(t)
    return out


def _process_media(db: Session, row: WhatsappInbox, data: dict) -> None:
    from weza.domains.need import service as journeys
    phone = data["phone"]

    def reply(text: str, reason: str) -> None:
        send_customer_message(db, phone, text, channel="whatsapp", kind="document")
        _finish(row, "DONE", reason)

    try:
        rate_limit(db, f"wa:media:{row.phone_index}", 10, 600)
    except RateLimited:
        return _finish(row, "DROPPED", "RATE_LIMITED")
    gi = _active_journey(db, row.phone_index)
    if gi is None:
        return reply(NEED_JOURNEY, "NO_JOURNEY")
    if not gi.state.get("customer_id"):
        return reply(VERIFY_FIRST, "NOT_VERIFIED")
    customer_id, need_id = uuid.UUID(gi.state["customer_id"]), uuid.UUID(gi.state["need_id"])
    try:
        media = whatsapp_media.fetch(data["media_id"])
    except whatsapp_media.MediaError as exc:
        log.warning("whatsapp_media_failed", extra={"data": {"err": exc.code}})
        return reply(TOO_LARGE if exc.code == "TOO_LARGE" else DOWNLOAD_FAILED, f"MEDIA_{exc.code}"[:40])
    doc_type = guess_doc_type(data.get("caption"), data.get("filename"),
                              _outstanding_doc_types(db, need_id, customer_id))
    d = docs.ingest(db, customer_id, doc_type=doc_type, filename=(data.get("filename") or "whatsapp-upload")[:200],
                    declared_mime=media.mime or data.get("mime") or "", data=media.data, need_id=need_id)
    if d.pipeline_state != "STORED":
        return reply((d.reject_reason or "I couldn't accept that file.") + " Please send a clear PDF, JPG or PNG.",
                     "DOC_REJECTED")
    label = docs.DOC_TYPES[doc_type]
    journeys._persist(db, gi, "IN", {"type": "text", "text": f"[Document sent: {label}]"}, "whatsapp",
                      row.provider_message_id)
    send_customer_message(db, phone, f"Got it. I've saved your {label.lower()} securely. "
                          "If it's the wrong type, just tell me which document it was.",
                          channel="whatsapp", kind="document")
    if gi.current_node == "REQUEST_MISSING_ITEM" and gi.status == "WAITING":
        journeys.system_resume(db, gi.id, "document_uploaded")
    _finish(row, "DONE", "DOC_STORED")
