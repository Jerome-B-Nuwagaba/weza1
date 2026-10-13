"""Public & channel endpoints: health, configuration, customer journeys (web/app), WhatsApp webhook + simulator,
institution applications."""

import hashlib
import hmac
import logging
import uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from weza.api.deps import DB, client_ip, optional_customer
from weza.config import get_settings
from weza.domains.admin_config import UGANDA, country
from weza.domains.consent import service as consent_svc
from weza.domains.institution import service as inst_svc
from weza.domains.institution.models import Institution
from weza.domains.misc_models import ChannelMessage
from weza.domains.need import service as journeys
from weza.domains.notification import service as notify
from weza.domains.need.models import ConversationMessage
from weza.domains.product.models import Product
from weza.platform import crypto
from weza.platform.controls import ai_mode, flag, rate_limit
from weza.platform.errors import Forbidden, NotFound, ValidationFailed
from weza.platform.models import GraphInstance

router = APIRouter(tags=["public"])
log = logging.getLogger("weza.whatsapp")


@router.get("/health")
def health(db: Session = DB):
    db.execute(text("select 1"))
    from sqlalchemy import func

    from weza.platform.models import EventDelivery
    lag = db.execute(select(func.min(EventDelivery.next_attempt_at)).where(EventDelivery.status == "PENDING")).scalar()
    from weza.domains.intelligence.ai import effective_mode
    return {"status": "ok", "env": get_settings().env, "ai_mode": effective_mode(db),
            "oldest_pending_event": lag.isoformat() if lag else None}


@router.get("/public/config")
def public_config(db: Session = DB):
    cfg = country(db)
    s = get_settings()
    return {"country": cfg["country_code"], "currency": cfg["currency"], "phone": cfg["phone"],
            "regions": cfg["regions"], "sectors": cfg["sectors"], "purpose_categories": cfg["purpose_categories"],
            "institution_types": cfg["institution_types"], "regulators": cfg["regulators"],
            "demo_mode": s.demo_mode and not s.is_production, "ai_mode": ai_mode(db),
            "whatsapp_live": s.whatsapp_send_ready, "features": {
                "whatsapp_simulator": flag(db, "channel.whatsapp_simulator", True),
                "preview": flag(db, "marketplace.preview", False)}}


@router.get("/public/stats")
def public_stats(db: Session = DB):
    from sqlalchemy import func
    insts = db.execute(select(Institution.display_name, Institution.institution_type).where(
        Institution.status == "ACTIVE").order_by(Institution.display_name)).all()
    return {"institutions": [{"name": n, "type": t} for n, t in insts],
            "active_products": db.execute(select(func.count()).select_from(Product).where(
                Product.status == "ACTIVE")).scalar_one()}


@router.get("/consent-templates/current")
def consent_template(institution: str = "the institution", db: Session = DB):
    return consent_svc.render(consent_svc.current_template(db), institution[:80])


# ------------------------------------------------------------------ journeys (web & app channel)


class StartJourney(BaseModel):
    channel: str = Field("web", pattern="^(web|app)$")
    text: str | None = Field(None, max_length=2000)
    src: str | None = Field(None, max_length=40)
    cmp: str | None = Field(None, max_length=40)
    ptn: str | None = Field(None, max_length=40)
    ref: str | None = Field(None, max_length=40)
    landing: str | None = Field(None, max_length=200)
    device_id: str | None = Field(None, max_length=120)


class JourneyInput(BaseModel):
    text: str | None = Field(None, max_length=2000)
    action: str | None = Field(None, max_length=40)
    value: str | None = Field(None, max_length=200)
    values: list[str] | None = None
    label: str | None = Field(None, max_length=80)
    categories: list[str] | None = None
    contact_channel: str | None = Field(None, max_length=16)
    contact_window: str | None = Field(None, max_length=40)
    message_id: str | None = Field(None, max_length=120)


def _journey_from_header(x_journey_token: str | None) -> uuid.UUID:
    if not x_journey_token:
        raise Forbidden("Missing conversation token.", code="JOURNEY_TOKEN_REQUIRED")
    return journeys.journey_id_from_token(x_journey_token)


@router.post("/journeys")
def start_journey(body: StartJourney, request: Request, db: Session = DB,
                  customer_id: uuid.UUID | None = Depends(optional_customer)):
    inst, outputs = journeys.start_journey(
        db, channel=body.channel, attribution=body.model_dump(include={"src", "cmp", "ptn", "ref", "landing"}),
        customer_id=customer_id, first_text=body.text, ip=client_ip(request),
        device_hash=crypto.sha256_hex(body.device_id) if body.device_id else None)
    return {"journey_id": str(inst.id), "token": journeys.journey_token(inst.id), "outputs": outputs,
            **journeys.view(db, inst.id)}


@router.get("/journeys/{journey_id}")
def get_journey(journey_id: uuid.UUID, x_journey_token: str | None = Header(None), db: Session = DB):
    if _journey_from_header(x_journey_token) != journey_id:
        raise Forbidden("Token does not match this conversation.")
    return journeys.view(db, journey_id)


@router.post("/journeys/{journey_id}/messages")
def post_message(journey_id: uuid.UUID, body: JourneyInput, x_journey_token: str | None = Header(None),
                 db: Session = DB):
    if _journey_from_header(x_journey_token) != journey_id:
        raise Forbidden("Token does not match this conversation.")
    gi = db.get(GraphInstance, journey_id)
    channel = (gi.state.get("channel") if gi else "web") or "web"
    outputs = journeys.handle_input(db, journey_id, body.model_dump(exclude_none=True), channel=channel,
                                    message_id=body.message_id)
    return {"outputs": outputs, **journeys.view(db, journey_id)}


# ------------------------------------------------------------------ WhatsApp channel gateway (TSD §5)


@router.get("/channels/whatsapp/webhook", response_class=PlainTextResponse)
def whatsapp_verify(hub_mode: str = Query(None, alias="hub.mode"), hub_token: str = Query(None, alias="hub.verify_token"),
                    hub_challenge: str = Query("", alias="hub.challenge")):
    s = get_settings()
    if hub_mode == "subscribe" and s.whatsapp_verify_ready and hmac.compare_digest(hub_token or "", s.whatsapp_verify_token):
        return hub_challenge
    raise Forbidden("Verification failed.")


@router.post("/channels/whatsapp/webhook")
async def whatsapp_webhook(request: Request, x_hub_signature_256: str | None = Header(None), db: Session = DB):
    s = get_settings()
    raw = await request.body()
    if not s.whatsapp_webhook_ready:
        raise Forbidden("WhatsApp is not configured.")
    expected = "sha256=" + hmac.new(s.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
        raise Forbidden("Invalid signature.")
    payload = await request.json()
    n_status = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            for st in value.get("statuses") or []:  # delivery receipts: update the message, never touch a journey
                errs = st.get("errors") or [{}]
                code = errs[0].get("code")
                n_status += notify.apply_delivery_status(
                    db, st.get("id", ""), st.get("status", ""), notify.parse_status_time(st.get("timestamp")),
                    str(code) if code is not None else None)
            for msg in value.get("messages", []):
                phone = "+" + msg.get("from", "").lstrip("+")
                text_ = (msg.get("text") or {}).get("body")
                reply = ((msg.get("interactive") or {}).get("button_reply") or {})
                inbound(db, phone, text=text_, button_id=reply.get("id"), button_title=reply.get("title"),
                        message_id=msg.get("id"))
    if n_status:
        log.info("whatsapp_statuses_applied", extra={"data": {"count": n_status}})
    return {"ok": True}


def inbound(db: Session, phone: str, *, text: str | None, button_id: str | None = None, button_title: str | None = None,
            message_id: str | None = None) -> list[dict]:
    """Canonical inbound handling for WhatsApp (real or simulated): find the active journey for this number or start one."""
    from weza.domains.intelligence.parsing import parse_phone
    phone_e164 = parse_phone(phone) or phone
    idx = crypto.blind_index("phone", phone_e164)
    rate_limit(db, f"wa:{idx}", 40, 600, "Too many messages. Please wait a moment.")
    gi = db.execute(select(GraphInstance).where(GraphInstance.graph_type == "customer_journey",
                                                GraphInstance.status.in_(["WAITING", "RUNNING"]),
                                                GraphInstance.state["wa_index"].astext == idx)
                    .order_by(GraphInstance.updated_at.desc()).limit(1)).scalar_one_or_none()
    if gi is None or (text or "").strip().lower() in ("restart", "new request", "start over"):
        from weza.domains.customer.models import Customer
        from weza.domains.identity.service import vault_find_by_phone
        rec = vault_find_by_phone(db, phone_e164)
        cust = db.execute(select(Customer).where(Customer.vault_token == rec.id)).scalar_one_or_none() if rec else None
        inst, outputs = journeys.start_journey(db, channel="whatsapp", attribution={"src": "whatsapp"},
                                               customer_id=cust.id if cust else None,
                                               first_text=text if text and text.strip().lower() not in
                                               ("hi", "hello", "hey", "restart", "start", "new request", "start over")
                                               else None, channel_phone=phone_e164)
        inst.state = {**inst.state, "wa_index": idx}
        return outputs
    payload: dict = {"text": text or button_title or ""}
    if button_id:
        if ":" in button_id:
            action, value = button_id.split(":", 1)
            payload.update({"action": action, "value": value})
        else:
            payload.update({"action": button_id, "value": None})
    return journeys.handle_input(db, gi.id, payload, channel="whatsapp", message_id=message_id)


class SimMessage(BaseModel):
    phone: str = Field(..., max_length=20)
    text: str | None = Field(None, max_length=2000)
    action: str | None = Field(None, max_length=40)
    value: str | None = Field(None, max_length=200)
    label: str | None = Field(None, max_length=80)


def _require_simulator(db: Session) -> None:
    s = get_settings()
    if s.is_production or not flag(db, "channel.whatsapp_simulator", True):
        raise NotFound("Not found.")


@router.post("/channels/simulator/messages")
def simulator_send(body: SimMessage, db: Session = DB):
    """WhatsApp simulator → the same gateway logic as the real webhook (blueprint C-03)."""
    _require_simulator(db)
    from weza.domains.intelligence.parsing import parse_phone
    if not parse_phone(body.phone):
        raise ValidationFailed("Use a Ugandan mobile number, e.g. 0772123456.")
    button = f"{body.action}:{body.value}" if body.action and body.value else body.action
    inbound(db, body.phone, text=body.text, button_id=button, button_title=body.label,
            message_id=f"sim:{uuid.uuid4()}")
    return simulator_inbox(body.phone, db)


@router.get("/channels/simulator/inbox")
def simulator_inbox(phone: str, db: Session = DB):
    """Messages WEZA sent to this number (WhatsApp + SMS) — simulator/test only."""
    _require_simulator(db)
    from weza.domains.intelligence.parsing import parse_phone
    p = parse_phone(phone)
    if not p:
        raise ValidationFailed("Invalid number.")
    idx = crypto.blind_index("phone", p)
    out = db.execute(select(ChannelMessage).where(ChannelMessage.to_index == idx).order_by(ChannelMessage.created_at)
                     .limit(300)).scalars().all()
    gi = db.execute(select(GraphInstance).where(GraphInstance.graph_type == "customer_journey",
                                                GraphInstance.state["wa_index"].astext == idx)
                    .order_by(GraphInstance.created_at.desc()).limit(1)).scalar_one_or_none()
    inbound_msgs = []
    if gi:
        inbound_msgs = [{"direction": "IN", "text": m.content.get("text") or m.content.get("label") or m.content.get("action"),
                         "at": m.received_at.isoformat()} for m in db.execute(
            select(ConversationMessage).where(ConversationMessage.session_id == gi.id,
                                              ConversationMessage.direction == "IN")).scalars()]
    msgs = [{"direction": "OUT", "channel": m.channel, "text": m.body,
             "quick_replies": (m.payload or {}).get("quick_replies", []), "at": m.created_at.isoformat()} for m in out]
    return {"messages": sorted(msgs + inbound_msgs, key=lambda m: m["at"]),
            "node": gi.current_node if gi else None}


# ------------------------------------------------------------------ institution application (Join WEZA)


class ContactIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    email: EmailStr
    phone: str = Field("", max_length=40)
    title: str = Field("", max_length=120)


class ApplicationIn(BaseModel):
    legal_name: str = Field(..., min_length=3, max_length=200)
    display_name: str | None = Field(None, max_length=120)
    institution_type: str
    licence_no: str = Field("", max_length=80)
    regulator: str = Field("", max_length=80)
    description: str = Field("", max_length=1000)
    website: str = Field("", max_length=200)
    representative: ContactIn
    business: ContactIn | None = None
    compliance: ContactIn
    admin_name: str = Field(..., min_length=2, max_length=160)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=12, max_length=200)
    accept_terms: bool


@router.post("/institutions/applications", status_code=201)
def apply(body: ApplicationIn, request: Request, db: Session = DB):
    rate_limit(db, f"apply:{crypto.sha256_hex(client_ip(request))}", 5, 3600)
    if body.institution_type not in UGANDA["institution_types"]:
        raise ValidationFailed("Choose an institution type.")
    inst, admin = inst_svc.apply(db, body.model_dump())
    return {"institution_id": str(inst.id), "status": inst.status,
            "message": "Application received. WEZA will verify your institution — you can sign in to continue setup."}
