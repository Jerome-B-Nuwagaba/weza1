"""WhatsApp inbound pipeline: acknowledge fast, process durably.

The webhook only verifies the signature and calls `receive()`, which stores one inbox row per provider message id
(unique → Meta retries are harmless) and emits an outbox event. The worker consumer then runs `process_phone()`,
which handles that number's pending messages in arrival order through the normal `public.inbound()` seam.
Message content is kept encrypted only until processed, then wiped. Nothing here logs phone numbers or text.

Failures: one number is processed by one worker at a time (advisory lock). An unexpected error rolls back that
message only; it is retried a few times with backoff (`retry_pending()`), later messages from the same number wait
behind it so order is kept, and after the last attempt it is marked FAILED, escalated for review and the customer is
told to try again. If a reply may already have reached the customer, the message is not retried (no duplicate replies).
"""

import json
import logging
import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from weza.domains.customer import documents as docs
from weza.domains.misc_models import WhatsappInbox
from weza.domains.notification import whatsapp_media
from weza.domains.notification.service import send_customer_message
from weza.platform import crypto
from weza.platform.controls import rate_limit
from weza.platform.db import utcnow
from weza.platform.errors import RateLimited, ValidationFailed, WezaError
from weza.platform.events import emit

log = logging.getLogger("weza.whatsapp")

UNSUPPORTED_REPLY = ("Sorry, I can only read typed messages and button taps for now. "
                     "Please type your message or tap one of the options.")
PROCESSING_FAILED_REPLY = ("Sorry, something went wrong on our side while handling your last message. "
                           "Please send it again in a few minutes.")
MAX_PROCESS_ATTEMPTS = 3
PROCESS_BACKOFF_SECONDS = 30  # multiplied by the attempt number
STALE_PENDING_SECONDS = 120  # a PENDING row this old with no retry scheduled lost its event: the sweep picks it up
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


_REF = re.compile(r"\s*\(ref:([A-Za-z0-9_.\-~]{0,163})\)\s*$")


def split_ref(text: str | None) -> tuple[str, dict]:
    """The website's "Continue on WhatsApp" link appends "(ref:src~cmp~ptn~ref)" to the first message. Returns the
    text without it plus the acquisition attribution (only non-empty parts)."""
    m = _REF.search(text or "")
    if not m:
        return text or "", {}
    parts = (m.group(1).split("~") + ["", "", "", ""])[:4]
    attribution = {k: v[:40] for k, v in zip(("src", "cmp", "ptn", "ref"), parts, strict=True) if v}
    return (text or "")[:m.start()].strip(), attribution


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


# account_update events after which WEZA can no longer send/receive on the number. With WhatsApp Business app
# coexistence this can happen without anyone touching WEZA: staff press Disconnect in the app, the phone re-registers,
# or Meta disconnects it for inactivity (disconnection_info.reason PRIMARY_INACTIVITY / COMPANION_INACTIVITY).
ACCOUNT_ALERT_EVENTS = {"PARTNER_REMOVED", "ACCOUNT_OFFBOARDED", "ACCOUNT_VIOLATION", "ACCOUNT_RESTRICTION",
                        "DISABLED_UPDATE"}


def account_update(db: Session, waba_id: str, at, value: dict) -> bool:
    """Handle an `account_update` webhook for our WABA. Returns True if an operations alert was raised."""
    from weza.config import get_settings, is_configured
    from weza.domains.integrity.service import add_review
    s = get_settings()
    if is_configured(s.whatsapp_business_account_id) and waba_id != s.whatsapp_business_account_id.strip():
        return False  # another account on the same Meta app
    event = str(value.get("event") or "UNKNOWN")[:40]
    info = value.get("disconnection_info") if isinstance(value.get("disconnection_info"), dict) else {}
    detail = {"event": event, "reason": str(info.get("reason") or "")[:40] or None,
              "initiated_by": str(info.get("initiated_by") or "")[:12] or None}  # never the phone number
    if event not in ACCOUNT_ALERT_EVENTS:
        log.info("whatsapp_account_update", extra={"data": detail})
        return False
    log.error("whatsapp_account_disconnected", extra={"data": detail})
    title = (f"WhatsApp account event {event}"
             + (f" ({detail['reason']}, by {detail['initiated_by']})" if detail["reason"] else "")
             + ": WEZA may no longer receive or answer customer messages. Run scripts/whatsapp_account_check.py and "
             "reconnect the number (docs/WHATSAPP_GO_LIVE.md).")
    add_review(db, "WHATSAPP_DISCONNECTED", title[:240], "channel", "whatsapp", severity="HIGH", detail=detail,
               dedupe_key=f"WHATSAPP_DISCONNECTED:{event}:{str(at or '')[:20]}")
    return True


def process_phone(db: Session, phone_index: str, now: datetime | None = None) -> int:
    """Process every due pending message for one number, oldest first. Returns how many were handled."""
    now = now or utcnow()
    # One worker per number at a time. Row locks alone don't cover a message that arrives while earlier ones are
    # being processed, so two first messages could otherwise start two journeys.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"wa:{phone_index}"})
    rows = db.execute(select(WhatsappInbox).where(WhatsappInbox.phone_index == phone_index,
                                                  WhatsappInbox.status == "PENDING")
                      .order_by(WhatsappInbox.received_at, WhatsappInbox.id).with_for_update()).scalars().all()
    n = 0
    for row in rows:
        if row.next_attempt_at and row.next_attempt_at > now:
            break  # waiting for a retry: later messages wait too, so the conversation stays in order
        n += 1
        if not _attempt(db, row, now):
            break
    return n


def _attempt(db: Session, row: WhatsappInbox, now: datetime) -> bool:
    """Process one message in its own savepoint. Returns False if it must be retried later."""
    db.info["wa_submitted"] = 0
    try:
        with db.begin_nested():
            _process_one(db, row)
        return True
    except Exception as exc:  # noqa: BLE001 — never let one message poison the number's queue
        submitted = db.info.get("wa_submitted", 0) > 0
        row.attempts = (row.attempts or 0) + 1
        # Type name only: exception text can carry SQL parameters (phone numbers, message text).
        log.warning("whatsapp_inbound_failed", extra={"data": {"err": type(exc).__name__, "attempts": row.attempts,
                                                               "reply_submitted": submitted}})
        if not submitted and row.attempts < MAX_PROCESS_ATTEMPTS:
            row.next_attempt_at = now + timedelta(seconds=PROCESS_BACKOFF_SECONDS * row.attempts)
            row.reason = f"RETRY:{type(exc).__name__}"[:40]
            return False
        _give_up(db, row, submitted, type(exc).__name__)
        return True
    finally:
        db.info.pop("wa_submitted", None)


def _give_up(db: Session, row: WhatsappInbox, reply_submitted: bool, err: str) -> None:
    from weza.domains.integrity.service import add_review
    reason = "PARTIAL_REPLY" if reply_submitted else "PROCESSING_ERROR"
    log.error("whatsapp_inbound_gave_up", extra={"data": {"reason": reason, "err": err}})
    if not reply_submitted:  # nothing reached the customer: tell them, rather than leave them in silence
        phone = json.loads(_dec_payload(row.payload_enc))["phone"]
        try:
            with db.begin_nested():
                send_customer_message(db, phone, PROCESSING_FAILED_REPLY, channel="whatsapp", kind="processing_error")
        except Exception:  # noqa: BLE001
            log.warning("whatsapp_apology_failed")
    add_review(db, "WHATSAPP_INBOUND_FAILED", f"A WhatsApp message could not be processed ({reason}, {err})",
               "whatsapp_inbox", row.id, severity="HIGH",
               detail={"reason": reason, "error": err, "attempts": row.attempts})
    _finish(row, "FAILED", reason)


def _dec_payload(token: str) -> str:
    from weza.domains.need.journey import _dec
    return _dec(token)


def retry_pending(db: Session, now: datetime | None = None, limit: int = 20) -> int:
    """Worker sweep: numbers whose oldest pending message is due for a retry, or whose queue event was lost
    (e.g. dead-lettered, or the worker stopped). Returns how many messages were handled."""
    now = now or utcnow()
    due = or_(WhatsappInbox.next_attempt_at <= now,
              WhatsappInbox.next_attempt_at.is_(None)
              & (WhatsappInbox.received_at <= now - timedelta(seconds=STALE_PENDING_SECONDS)))
    phones = db.execute(select(WhatsappInbox.phone_index).where(WhatsappInbox.status == "PENDING", due)
                        .group_by(WhatsappInbox.phone_index).order_by(func.min(WhatsappInbox.received_at))
                        .limit(limit)).scalars().all()
    return sum(process_phone(db, p, now) for p in phones)


def _finish(row: WhatsappInbox, status: str, reason: str | None = None) -> None:
    row.status, row.reason, row.payload_enc, row.processed_at = status, reason, None, utcnow()


def _process_one(db: Session, row: WhatsappInbox) -> None:
    from weza.api.v1 import public
    data = json.loads(_dec_payload(row.payload_enc))
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
    text, attribution = split_ref(data["text"])
    try:
        with db.begin_nested():
            public.inbound(db, phone, text=text, button_id=data["button_id"], button_title=data["button_title"],
                           message_id=row.provider_message_id, attribution=attribution or None)
    except WezaError as exc:  # rate limited / invalid message: permanent for this message → acknowledge, don't retry
        log.info("whatsapp_inbound_dropped", extra={"data": {"reason": exc.code}})
        if isinstance(exc, ValidationFailed):  # e.g. message too long: say why instead of going silent
            try:
                rate_limit(db, f"wa:invalid:{row.phone_index}", 3, 600)
                send_customer_message(db, phone, exc.message, channel="whatsapp", kind="invalid_message")
            except RateLimited:
                pass
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
    from weza.domains.consent.models import Consent
    from weza.domains.customer.models import Document
    from weza.domains.matching.models import Match
    from weza.domains.opportunity.models import InfoRequest, Opportunity
    have = set(db.execute(select(Document.doc_type).where(Document.customer_id == customer_id,
                                                          Document.pipeline_state == "STORED")).scalars())
    out: list[str] = list(db.execute(select(InfoRequest.doc_type).join(
        Opportunity, Opportunity.id == InfoRequest.opportunity_id).join(Consent, Consent.id == Opportunity.consent_id)
        .where(InfoRequest.customer_id == customer_id, Opportunity.customer_id == customer_id,
               InfoRequest.institution_id == Opportunity.institution_id, Consent.customer_id == customer_id,
               Consent.institution_id == Opportunity.institution_id, Consent.status == "GRANTED",
               InfoRequest.kind == "DOCUMENT", InfoRequest.status == "OPEN")
        .order_by(InfoRequest.created_at)).scalars())
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
    from weza.domains.need.journey import fulfil_info
    outputs = fulfil_info(db, customer_id, document_id=d.id, doc_type=doc_type)
    if outputs:
        journeys._persist_outputs(db, gi, outputs, "whatsapp")
        return _finish(row, "DONE", "INFO_FULFILLED")
    send_customer_message(db, phone, f"Got it. I've saved your {label.lower()} securely. "
                          "If it's the wrong type, just tell me which document it was.",
                          channel="whatsapp", kind="document")
    if gi.current_node == "REQUEST_MISSING_ITEM" and gi.status == "WAITING":
        journeys.system_resume(db, gi.id, "document_uploaded")
    _finish(row, "DONE", "DOC_STORED")
