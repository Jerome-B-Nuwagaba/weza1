"""Journey service: starts/resumes the customer conversation graph and persists the canonical message
contract (TSD §5–7). Web, Flutter and WhatsApp all call these functions."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from weza.domains.commercial.service import record_attribution
from weza.domains.need import journey
from weza.domains.need.models import ConversationMessage, FinancialNeed
from weza.platform import crypto
from weza.platform.context import correlation_id
from weza.platform.controls import channel_disabled, rate_limit
from weza.platform.errors import Forbidden, NotFound, ValidationFailed
from weza.platform.events import emit
from weza.platform.graph import Trigger, load_for_update, resume, start
from weza.platform.models import GraphInstance


def journey_token(journey_id: uuid.UUID) -> str:
    return crypto.sign_jwt({"typ": "journey", "jid": str(journey_id)}, 60 * 24 * 30)


def journey_id_from_token(token: str) -> uuid.UUID:
    try:
        claims = crypto.verify_jwt(token)
    except Exception as exc:  # noqa: BLE001
        raise Forbidden("Your conversation link has expired. Please start again.", code="JOURNEY_TOKEN_INVALID") from exc
    if claims.get("typ") != "journey":
        raise Forbidden("Invalid conversation token.")
    return uuid.UUID(claims["jid"])


def start_journey(db: Session, *, channel: str, attribution: dict | None = None, customer_id: uuid.UUID | None = None,
                  first_text: str | None = None, channel_phone: str | None = None, ip: str = "",
                  device_hash: str | None = None, message_id: str | None = None) -> tuple[GraphInstance, list[dict]]:
    if channel_disabled(db, channel):
        raise ValidationFailed("This channel is temporarily unavailable. Please try another.", code="CHANNEL_DISABLED")
    if ip:
        rate_limit(db, f"journey:ip:{crypto.sha256_hex(ip)}", 30, 3600)
    a = attribution or {}
    attr = record_attribution(db, source=a.get("src"), campaign=a.get("cmp"), partner=a.get("ptn"),
                              referral=a.get("ref"), channel=channel, landing=a.get("landing"))
    need = FinancialNeed(customer_id=customer_id, status="DRAFT", attribution_id=attr.id)
    db.add(need)
    db.flush()
    state = {"need_id": str(need.id), "channel": channel, "ip": crypto.sha256_hex(ip) if ip else "",
             "device_hash": device_hash, "intent": {}, "customer_id": str(customer_id) if customer_id else None}
    if first_text:
        state["first_text"] = first_text
    if channel_phone:
        state["channel_phone_enc"] = journey._enc(channel_phone)
    inst, outputs = start(db, journey.GRAPH, state, need_id=need.id, customer_id=customer_id)
    need.journey_id = inst.id
    emit(db, "NeedCreated", topic="customer", aggregate_type="need", aggregate_id=need.id,
         data={"channel": channel, "source": a.get("src") or "direct"})
    if first_text:
        _persist(db, inst, "IN", {"type": "text", "text": first_text}, channel, message_id)
    _persist_outputs(db, inst, outputs, channel)
    return inst, outputs


def handle_input(db: Session, journey_id: uuid.UUID, payload: dict, *, channel: str, message_id: str | None = None
                 ) -> list[dict]:
    """Inbound customer message → canonical message → graph resume. Duplicate channel message IDs are ignored
    (at-least-once webhooks)."""
    inst = load_for_update(db, journey_id)
    if message_id and db.execute(select(ConversationMessage.id).where(ConversationMessage.message_id == message_id)).first():
        return []
    text = (payload.get("text") or "").strip()
    if len(text) > 2000:
        raise ValidationFailed("Message is too long.")
    rate_limit(db, f"journey:msg:{journey_id}", 60, 600, "You're sending messages very quickly. Please wait a moment.")
    shown = {"type": "text", "text": text} if text else {"type": "action", "action": payload.get("action"),
                                                         "label": payload.get("label")}
    if inst.state.get("pending_q", {}).get("type") in ("nin", "name") and inst.current_node == "ASK_PROFILE":
        shown = {"type": "text", "text": "•••• (hidden)"}  # never keep identity values in conversation history
    if inst.current_node in ("VERIFY_PHONE", "PAYOUT_NUMBER") or (inst.current_node == "CRB_CHECK"
                                                                   and inst.state.get("crb_challenge_id")):
        shown = {"type": "text", "text": "•••• (hidden)"}
    _persist(db, inst, "IN", shown, channel, message_id)
    if inst.status in ("COMPLETED", "EXPIRED", "CANCELLED", "FAILED"):
        return [{"type": "text", "text": "This conversation has ended. Start a new request any time."}]
    outputs = resume(db, inst, Trigger("CUSTOMER_REPLY", payload, actor="customer"))
    _persist_outputs(db, inst, outputs, channel)
    return outputs


def system_resume(db: Session, journey_id: uuid.UUID, action: str, value: str | None = None, **extra) -> list[dict]:
    """Resume a journey from a marketplace event (waiting-room match, reported decline)."""
    inst = load_for_update(db, journey_id)
    if inst.status in ("COMPLETED", "EXPIRED", "CANCELLED", "FAILED"):
        return []
    outputs = resume(db, inst, Trigger("CUSTOMER_REPLY", {"action": action, "value": value, "_any": True, **extra},
                                       actor="system"))
    _persist_outputs(db, inst, outputs, inst.state.get("channel", "web"))
    return outputs


def _persist(db: Session, inst: GraphInstance, direction: str, content: dict, channel: str, message_id: str | None,
             at=None):
    msg = ConversationMessage(message_id=message_id or f"weza:{uuid.uuid4()}", session_id=inst.id,
                              customer_id=inst.customer_id, channel=channel, direction=direction,
                              message_type="TEXT" if content.get("type") == "text" else "BUTTON_RESPONSE"
                              if direction == "IN" else "SYSTEM_MESSAGE", content=content,
                              correlation_id=correlation_id(), **({"received_at": at} if at else {}))
    try:
        with db.begin_nested():
            db.add(msg)
    except IntegrityError:
        pass


def _persist_outputs(db: Session, inst: GraphInstance, outputs: list[dict], channel: str) -> None:
    from datetime import timedelta

    from weza.platform.db import utcnow
    base = utcnow()
    # Explicit microsecond offsets keep outputs in the order the graph produced them.
    for i, o in enumerate(journey.format_for_channel(outputs), start=1):
        _persist(db, inst, "OUT", o, channel, None, at=base + timedelta(microseconds=i))
    if channel == "whatsapp":
        _send_whatsapp(db, inst, outputs)


def _send_whatsapp(db: Session, inst: GraphInstance, outputs: list[dict]) -> None:
    from weza.config import get_settings
    from weza.domains.customer.models import Customer
    from weza.domains.identity.service import vault_read
    from weza.domains.notification.service import send_customer_message
    phone = None
    if inst.customer_id:
        c = db.get(Customer, inst.customer_id)
        phone = vault_read(db, c.vault_token).get("phone") if c else None
    if not phone and inst.state.get("channel_phone_enc"):
        phone = journey._dec(inst.state["channel_phone_enc"])
    if not phone:
        return
    web = get_settings().public_web_url
    for o in outputs:
        text = journey.whatsapp_text(o)
        if text:
            send_customer_message(db, phone, text.replace("{web}", web), channel="whatsapp",
                                  kind="sensitive" if o.get("ephemeral") else "conversation",
                                  payload={"quick_replies": o.get("quick_replies") or []})


def view(db: Session, journey_id: uuid.UUID, limit: int = 200) -> dict:
    inst = db.get(GraphInstance, journey_id)
    if inst is None or inst.graph_type != "customer_journey":
        raise NotFound("Conversation not found.")
    msgs = db.execute(select(ConversationMessage).where(ConversationMessage.session_id == journey_id)
                      .order_by(ConversationMessage.received_at, ConversationMessage.id).limit(limit)).scalars().all()
    need = db.get(FinancialNeed, uuid.UUID(inst.state["need_id"]))
    last_in = max((i for i, m in enumerate(msgs) if m.direction == "IN"), default=-1)
    latest_outs = [m.content for m in msgs[last_in + 1:] if m.direction == "OUT"]
    pending_qr = next((o.get("quick_replies") for o in reversed(latest_outs) if o.get("quick_replies")), [])
    return {
        "journey_id": str(inst.id), "node": inst.current_node, "status": inst.status,
        "waiting_for": inst.waiting_for, "need": need_summary(need),
        "messages": [{"direction": m.direction, "at": m.received_at.isoformat(), **m.content} for m in msgs],
        "quick_replies": pending_qr if inst.status == "WAITING" else [],
        "verified": bool(inst.state.get("customer_id")),
    }


def need_summary(need: FinancialNeed) -> dict:
    return {"id": str(need.id), "status": need.status, "amount": float(need.amount) if need.amount else None,
            "currency": need.currency, "purpose": need.purpose, "purpose_category": need.purpose_category,
            "customer_type": need.customer_type, "sector": need.sector, "district": need.district,
            "readiness": need.readiness, "quality_score": need.quality_score,
            "intent_confirmed": need.intent_confirmed_at is not None,
            "created_at": need.created_at.isoformat() if need.created_at else None,
            "waiting_until": need.waiting_until.isoformat() if need.waiting_until else None}
