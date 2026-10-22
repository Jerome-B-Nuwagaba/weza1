"""Customer Conversation Graph `customer_journey` v1 (Skill §16; blueprint G1; TSD §7).

State is persisted in platform.graph_instance — never in chat history. Every waiting node has a timeout.
Channel-agnostic: web, Flutter and WhatsApp all drive the same graph through the canonical message contract.
"""

import base64
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from weza.domains.admin_config import UGANDA, region_of
from weza.domains.consent import service as consent_svc
from weza.domains.customer import service as customer_svc
from weza.domains.customer.models import Customer, Preference
from weza.domains.identity import service as identity
from weza.domains.institution.models import Institution, ServiceTarget
from weza.domains.intelligence import agents, parsing
from weza.domains.matching import engine
from weza.domains.matching.models import Match
from weza.domains.matching.rules import fmt, fmt_money
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import Opportunity
from weza.domains.trust.service import audit
from weza.platform import crypto
from weza.platform.context import Actor
from weza.platform.db import utcnow
from weza.platform.errors import ValidationFailed
from weza.platform.events import emit
from weza.platform.graph import Ctx, GraphDef, Node, Step, Trigger, Wait, register

DAY = 86400
REPLY = "CUSTOMER_REPLY"
MAX_INTENT_TURNS = 8
MAX_PROFILE_QUESTIONS = 25
MAX_ANSWER_ATTEMPTS = 3
CRITICAL_CONFIDENCE = 0.85
CUSTOMER_TYPE_LABELS = {"SME": "Business owner", "SALARIED": "Salaried employee", "AGRICULTURE": "Farmer"}
RANKING_PREFS = {"LOWER_MONTHLY_PAYMENT": "Lower monthly payment", "LOW_COLLATERAL": "Little or no collateral",
                 "FAST_RESPONSE": "Fast response", "DIGITAL": "Digital process", "NEAR_ME": "Near me",
                 "SHORTER_TENOR": "Shorter repayment"}


def qr(label: str, action: str, value: str | None = None) -> dict:
    return {"label": label, "action": action, "value": value}


def _need(ctx: Ctx, st: dict) -> FinancialNeed:
    return ctx.db.get(FinancialNeed, uuid.UUID(st["need_id"]))


def _customer_actor(st: dict) -> Actor:
    cid = st.get("customer_id")
    return Actor(kind="CUSTOMER", id=uuid.UUID(cid) if cid else None, display="customer")


def _text(t: Trigger) -> str:
    return (t.payload.get("text") or "").strip()


def _action(t: Trigger) -> str | None:
    a = t.payload.get("action")
    if a:
        return a
    tx = _text(t).lower()
    return {"yes": "confirm", "yes, that's right": "confirm", "correct": "confirm", "skip": "skip",
            "no": "no", "agree": "agree", "i agree": "agree"}.get(tx)


def _intent_complete(intent: dict) -> list[str]:
    missing = []
    if not intent.get("amount"):
        missing.append("amount")
    if not (intent.get("purpose") or intent.get("purpose_category")):
        missing.append("purpose")
    if not intent.get("customer_type"):
        missing.append("customer_type")
    return missing


def _apply_intent(ctx: Ctx, st: dict, extracted: dict, overwrite: bool) -> dict:
    intent = dict(st.get("intent") or {})
    conf = dict(intent.get("confidence") or {})
    for k in ("amount", "purpose", "purpose_category", "customer_type", "sector", "district", "tenor_months",
              "urgency", "product_family"):
        v = extracted.get(k)
        if v is not None and (overwrite or not intent.get(k)):
            intent[k] = v
            ck = "purpose" if k == "purpose_category" else k
            if ck in (extracted.get("confidence") or {}):
                conf[ck] = extracted["confidence"][ck]
    intent["confidence"] = conf
    need = _need(ctx, st)
    need.amount = Decimal(str(intent["amount"])) if intent.get("amount") else None
    need.purpose = intent.get("purpose") or (UGANDA["purpose_categories"].get(intent.get("purpose_category") or ""))
    need.purpose_category = intent.get("purpose_category")
    need.customer_type = intent.get("customer_type")
    need.sector = intent.get("sector")
    need.district = intent.get("district") or need.district
    need.region = region_of(need.district)
    need.tenor_months = intent.get("tenor_months")
    need.urgency = intent.get("urgency")
    need.product_family = intent.get("product_family") or parsing.FAMILY_BY_PURPOSE.get(need.purpose_category or "")
    need.status = "INTENT_CAPTURE"
    vals = [v for k, v in conf.items() if k in ("amount", "purpose", "customer_type")]
    need.intent_confidence = min(vals) if vals else None
    return intent


# ------------------------------------------------------------------ nodes


def greet(ctx: Ctx, st: dict, t: Trigger) -> Step:
    if t.kind == "ENTER":
        if st.get("first_text"):
            return Step(to="UNDERSTAND_INTENT", patch={"last_text": st["first_text"], "first_text": None})
        ctx.say("Welcome to WEZA. Tell me what you would like financing for.",
                hint="For example: I need UGX 30 million to expand my pharmacy.")
        return Step(wait=Wait(REPLY, DAY))
    text = _text(t)
    if not text:
        ctx.say("Tell me in your own words what you need financing for.")
        return Step(wait=Wait(REPLY, DAY))
    return Step(to="UNDERSTAND_INTENT", patch={"last_text": text})


def understand_intent(ctx: Ctx, st: dict, t: Trigger) -> Step:
    patch: dict = {"intent_turns": st.get("intent_turns", 0) + 1}
    if st.get("last_text"):
        extracted = agents.customer_intent(ctx.db, st["last_text"], subject=st["need_id"])
        patch["intent"] = _apply_intent(ctx, st, extracted, overwrite=False)
        patch["last_text"] = None
    intent = patch.get("intent") or st.get("intent") or {}
    missing = _intent_complete(intent)
    if missing and patch["intent_turns"] > MAX_INTENT_TURNS:
        return Step(to="SAVE_EXIT", patch={**patch, "exit_reason": "intent_budget"})
    if missing:
        return Step(to="ASK_INTENT", patch={**patch, "pending_intent": missing[0], "answer_attempts": 0})
    return Step(to="CONFIRM_INTENT", patch=patch)


def ask_intent(ctx: Ctx, st: dict, t: Trigger) -> Step:
    field = st["pending_intent"]
    if t.kind == "ENTER":
        if field == "amount":
            ctx.say("How much financing do you need?", hint="e.g. UGX 5 million")
        elif field == "purpose":
            ctx.say("What will you use the money for?", quick_replies=[
                qr(lbl, "purpose", code) for code, lbl in list(UGANDA["purpose_categories"].items())[:8]])
        else:
            ctx.say("Which best describes you?", quick_replies=[qr(v, "customer_type", k)
                                                                for k, v in CUSTOMER_TYPE_LABELS.items()])
        return Step(wait=Wait(REPLY, DAY))
    text, value = _text(t), t.payload.get("value")
    intent = dict(st.get("intent") or {})
    conf = dict(intent.get("confidence") or {})
    if field == "amount":
        amt = parsing.parse_money_answer(text) if text else None
        if not amt or amt <= 0:
            return _reask(ctx, st, "I didn't catch the amount. Please type it like 'UGX 5,000,000' or '5 million'.")
        intent["amount"], conf["amount"] = float(amt), 1.0
    elif field == "purpose":
        if value and value in UGANDA["purpose_categories"]:
            intent["purpose_category"], intent["purpose"] = value, UGANDA["purpose_categories"][value]
        else:
            cat, phrase, _ = parsing.parse_purpose(text)
            if not text:
                return _reask(ctx, st, "Tell me briefly what the money is for.")
            intent["purpose_category"] = intent.get("purpose_category") or cat
            intent["purpose"] = phrase or text[:120]
        conf["purpose"] = 1.0
    else:
        ctype = value if value in CUSTOMER_TYPE_LABELS else parsing.parse_customer_type(text)[0]
        if not ctype:
            return _reask(ctx, st, "Please choose the option that best describes you.")
        intent["customer_type"], conf["customer_type"] = ctype, 1.0
    intent["confidence"] = conf
    st2 = {**st, "intent": intent}
    _apply_intent(ctx, st2, {}, overwrite=False)
    return Step(to="UNDERSTAND_INTENT", patch={"intent": intent, "last_text": text if field == "amount" else None})


def _reask(ctx: Ctx, st: dict, msg: str) -> Step:
    attempts = st.get("answer_attempts", 0) + 1
    if attempts >= MAX_ANSWER_ATTEMPTS * 2:
        return Step(to="SAVE_EXIT", patch={"answer_attempts": 0, "exit_reason": "unparsed_answers"})
    ctx.say(msg)
    return Step(wait=Wait(REPLY, DAY), patch={"answer_attempts": attempts})


def confirm_intent(ctx: Ctx, st: dict, t: Trigger) -> Step:
    intent = st.get("intent") or {}
    if t.kind == "ENTER":
        conf = intent.get("confidence") or {}
        sector = UGANDA["sectors"].get(intent.get("sector") or "")
        ctx.card("understanding", {
            "amount": fmt_money(intent.get("amount") or 0), "amount_value": intent.get("amount"),
            "purpose": intent.get("purpose") or UGANDA["purpose_categories"].get(intent.get("purpose_category") or ""),
            "customer_type": CUSTOMER_TYPE_LABELS.get(intent.get("customer_type") or ""),
            "sector": sector, "district": intent.get("district"),
            "needs_confirmation": [k for k in ("amount", "purpose", "customer_type")
                                   if (conf.get(k) or 0) < CRITICAL_CONFIDENCE],
        })
        ctx.say("Here's what I understood. Is this right?",
                quick_replies=[qr("Yes, that's right", "confirm"), qr("Change something", "change")])
        return Step(wait=Wait(REPLY, DAY))
    action = _action(t)
    if action == "confirm":
        need = _need(ctx, st)
        need.intent_confirmed_at = utcnow()
        need.status = "INTENT_CONFIRMED"
        conf = {k: 1.0 for k in ("amount", "purpose", "customer_type")}
        intent = {**intent, "confidence": {**(intent.get("confidence") or {}), **conf}}
        emit(ctx.db, "IntentConfirmed", topic="customer", aggregate_type="need", aggregate_id=need.id,
             data={"amount": str(need.amount), "purpose_category": need.purpose_category,
                   "customer_type": need.customer_type})
        nxt = "BUILD_PROFILE" if st.get("customer_id") else "VERIFY_PHONE"
        if st.get("customer_id"):
            _sync_customer_from_intent(ctx, st)
        return Step(to=nxt, patch={"intent": intent})
    if action == "change":
        ctx.say("Tell me what's different — for example 'the amount is 25 million' or 'it's for buying stock'.")
        return Step(wait=Wait(REPLY, DAY))
    text = _text(t)
    if not text:
        return Step(wait=Wait(REPLY, DAY))
    return Step(to="REVISE_INTENT", patch={"last_text": text})


def revise_intent(ctx: Ctx, st: dict, t: Trigger) -> Step:
    text = st.get("last_text") or ""
    extracted = agents.customer_intent(ctx.db, text, subject=st["need_id"])
    amt = parsing.parse_money_answer(text)
    if extracted.get("amount") is None and amt:
        extracted["amount"], extracted["confidence"]["amount"] = float(amt), 1.0
    ctype, c = parsing.parse_customer_type(text)
    if ctype and c >= 0.9:
        extracted["customer_type"] = ctype
    intent = _apply_intent(ctx, st, extracted, overwrite=True)
    return Step(to="CONFIRM_INTENT", patch={"intent": intent, "last_text": None})


def _enc(s: str) -> str:
    ct, wk = crypto.encrypt_bytes(s.encode())
    return base64.b64encode(wk).decode() + "." + base64.b64encode(ct).decode()


def _dec(s: str) -> str:
    wk, ct = s.split(".")
    return crypto.decrypt_bytes(base64.b64decode(ct), base64.b64decode(wk)).decode()


def verify_phone(ctx: Ctx, st: dict, t: Trigger) -> Step:
    if st.get("customer_id"):
        return Step(to="BUILD_PROFILE")
    if t.kind == "ENTER":
        if st.get("channel") == "whatsapp" and st.get("channel_phone_enc") and not st.get("otp_challenge_id"):
            # The customer is writing from this number and Meta authenticated the sender (signed webhook). A code
            # sent back into the same chat proves nothing new, so the channel itself verifies the number.
            # Web/app keep the OTP: a browser proves nothing about a phone, and the OTP issues their session.
            return _phone_verified(ctx, st, _dec(st["channel_phone_enc"]), method="whatsapp_channel")
        if st.get("channel_phone_enc") and not st.get("otp_challenge_id"):
            return _send_otp(ctx, st, _dec(st["channel_phone_enc"]))
        if st.get("otp_challenge_id"):
            ctx.say("Enter the 6-digit code we sent you.", quick_replies=[qr("Resend code", "resend"),
                                                                          qr("Change number", "change_number")])
            ctx.card("otp_input", {"masked": st.get("phone_masked")})
            return Step(wait=Wait("CUSTOMER_REPLY", DAY))
        ctx.say("To keep your request secure, please enter your mobile number. We'll send you a 6-digit code.",
                hint=f"e.g. {UGANDA['phone']['example']}")
        ctx.card("phone_input", {"prefix": UGANDA["phone"]["prefix"]})
        return Step(wait=Wait(REPLY, DAY))
    action = _action(t)
    if action == "change_number":
        ctx.say("OK — what mobile number should we use?")
        ctx.card("phone_input", {"prefix": UGANDA["phone"]["prefix"]})
        return Step(wait=Wait(REPLY, DAY), patch={"otp_challenge_id": None, "phone_enc": None, "channel_phone_enc": None})
    if action == "resend" and st.get("phone_enc"):
        return _send_otp(ctx, st, _dec(st["phone_enc"]))
    text = _text(t) or str(t.payload.get("value") or "")
    if not st.get("otp_challenge_id"):
        phone = parsing.parse_phone(text)
        if not phone:
            ctx.say(f"That doesn't look like a valid Ugandan mobile number. Please try again, e.g. "
                    f"{UGANDA['phone']['example']}.")
            return Step(wait=Wait(REPLY, DAY))
        return _send_otp(ctx, st, phone)
    code = "".join(ch for ch in text if ch.isdigit())
    res = identity.verify_otp(ctx.db, uuid.UUID(st["otp_challenge_id"]), code)
    if not res.ok:
        ctx.say(res.message, quick_replies=[qr("Resend code", "resend"), qr("Change number", "change_number")])
        patch = {"otp_challenge_id": None} if res.code in ("OTP_LOCKED", "OTP_EXPIRED") else {}
        emit(ctx.db, "PhoneVerificationFailed", topic="customer", aggregate_type="need", aggregate_id=st["need_id"],
             data={"code": res.code})
        return Step(wait=Wait(REPLY, DAY), patch=patch)
    return _phone_verified(ctx, st, _dec(st["phone_enc"]), method="otp")


def _phone_verified(ctx: Ctx, st: dict, phone: str, *, method: str) -> Step:
    """The phone is proven (OTP, or the WhatsApp channel itself): link or create the customer and continue."""
    need = _need(ctx, st)
    customer, is_new = customer_svc.get_or_create_by_phone(ctx.db, phone, attribution_id=need.attribution_id,
                                                           device_hash=st.get("device_hash"))
    need.customer_id = customer.id
    need.status = "PHONE_VERIFIED"
    need.phone_verified = True
    need.phone_verified_at = utcnow()
    need.phone_verification_method = "OTP" if method == "otp" else "WHATSAPP_CHANNEL"
    ctx.instance.customer_id = customer.id
    if method == "otp":  # web/app need a session; WhatsApp is identified by the chat itself
        token = identity.create_customer_session(ctx.db, customer.id, st.get("channel", "web"))
        ctx.card("session", {"token": token, "customer_id": str(customer.id), "returning": not is_new})
    audit(ctx.db, Actor(kind="CUSTOMER", id=customer.id, display="customer"), "customer.phone_verified", "customer",
          customer.id, after={"method": method})
    emit(ctx.db, "PhoneVerified", topic="customer", aggregate_type="need", aggregate_id=need.id,
         data={"returning": not is_new, "method": method})
    if method == "otp":
        ctx.say("Thank you — your number is verified." + (" Welcome back!" if not is_new else ""))
    elif not is_new:
        ctx.say("Welcome back!")
    if st.get("channel") == "whatsapp":
        from weza.domains.customer.auth import issue_magic_link
        ctx.say("Open your requests, profile and documents securely: " + issue_magic_link(ctx.db, customer.id),
                ephemeral=True)
    st2 = {**st, "customer_id": str(customer.id)}
    _sync_customer_from_intent(ctx, st2)
    return Step(to="BUILD_PROFILE", patch={"customer_id": str(customer.id), "otp_challenge_id": None,
                                           "phone_enc": None, "channel_phone_enc": None})


def _send_otp(ctx: Ctx, st: dict, phone: str) -> Step:
    res = identity.issue_otp(ctx.db, phone, ip=st.get("ip", ""), journey_id=ctx.instance.id)
    patch = {"phone_enc": _enc(phone), "phone_masked": identity.mask_phone(phone)}
    if not res.ok and res.code not in ("OTP_COOLDOWN",):
        ctx.say(res.message, quick_replies=[qr("Change number", "change_number")])
        return Step(wait=Wait(REPLY, DAY), patch=patch)
    if res.challenge is not None and res.ok:
        patch["otp_challenge_id"] = str(res.challenge.id)
    ctx.say(res.message if res.ok else "Please wait a moment, then use the code we already sent.",
            quick_replies=[qr("Resend code", "resend"), qr("Change number", "change_number")])
    ctx.card("otp_input", {"masked": patch["phone_masked"], "dev_code": res.dev_code})
    return Step(wait=Wait(REPLY, DAY), patch=patch)


def _sync_customer_from_intent(ctx: Ctx, st: dict) -> None:
    need = _need(ctx, st)
    cust = ctx.db.get(Customer, uuid.UUID(st["customer_id"]))
    cust.customer_type = need.customer_type
    if need.sector and need.customer_type == "SME":
        customer_svc.upsert_fact(ctx.db, cust.id, "business.sector", need.sector, source="CUSTOMER",
                                 channel=st.get("channel", "web"), confirmed=True, source_ref="intent")
    if need.tenor_months:
        customer_svc.upsert_fact(ctx.db, cust.id, "need.tenor_months", need.tenor_months, source="CUSTOMER",
                                 channel=st.get("channel", "web"), confirmed=True, source_ref="intent")


def build_profile(ctx: Ctx, st: dict, t: Trigger) -> Step:
    need = _need(ctx, st)
    if need.status in ("PHONE_VERIFIED", "INTENT_CONFIRMED"):
        need.status = "PROFILE_IN_PROGRESS"
    skipped = set(st.get("skipped") or [])
    qs = [q for q in customer_svc.missing_questions(ctx.db, need, uuid.UUID(st["customer_id"])) if q["key"] not in skipped]
    if not qs or st.get("profile_questions", 0) >= MAX_PROFILE_QUESTIONS:
        return Step(to="READINESS_CHECK")
    return Step(to="ASK_PROFILE", patch={"pending_q": qs[0], "answer_attempts": 0})


def ask_profile(ctx: Ctx, st: dict, t: Trigger) -> Step:
    q = st["pending_q"]
    if t.kind == "ENTER":
        replies = []
        if q["type"] == "choice":
            replies = [qr(lbl, "answer", val) for val, lbl in q["options"]]
        elif q["type"] == "yesno":
            replies = [qr("Yes", "answer", "yes"), qr("No", "answer", "no")]
        elif q["type"] == "sector":
            replies = [qr(lbl, "answer", code) for code, lbl in UGANDA["sectors"].items()]
        if not q.get("required"):
            replies.append(qr("Skip", "skip"))
        ctx.say(q["prompt"], quick_replies=replies)
        ctx.card("question", {"key": q["key"], "type": q["type"], "required": q.get("required", False),
                              "options": q.get("options"), "progress": _progress(ctx, st)})
        return Step(wait=Wait(REPLY, DAY), patch={"profile_questions": st.get("profile_questions", 0) + 1})
    if _action(t) == "skip" and not q.get("required"):
        return Step(to="BUILD_PROFILE", patch={"skipped": [*(st.get("skipped") or []), q["key"]]})
    raw = t.payload.get("value") if t.payload.get("value") not in (None, "") else _text(t)
    value = _parse_answer(q, str(raw))
    source, confidence = "CUSTOMER", 1.0
    if value is None and str(raw).strip():
        ai_val, ai_conf = agents.customer_profile_answer(ctx.db, q, str(raw), subject=st["need_id"])
        if ai_val is not None and ai_conf >= CRITICAL_CONFIDENCE:
            value = _parse_answer(q, str(ai_val))
            source, confidence = "AI_EXTRACTED", ai_conf
    if value is None:
        if q["type"] == "nin" and str(raw).strip().lower() in ("skip", "no", "none"):
            return Step(to="BUILD_PROFILE", patch={"skipped": [*(st.get("skipped") or []), q["key"]]})
        return _reask(ctx, st, _help_for(q))
    cust_id = uuid.UUID(st["customer_id"])
    fact, conflict = customer_svc.upsert_fact(ctx.db, cust_id, q["key"], value, source=source,
                                              channel=st.get("channel", "web"), confidence=confidence,
                                              confirmed=source == "CUSTOMER")
    if conflict is not None:
        return Step(to="RESOLVE_CONFLICT", patch={"conflict": {"key": q["key"], "old": conflict.value.get("v"),
                                                               "new": value, "type": q["type"]}})
    need = _need(ctx, st)
    if q["key"] in ("business.district", "residence.district", "farm.district"):
        need.district, need.region = value, region_of(value)
    if q["key"] == "need.tenor_months":
        need.tenor_months = value
    if q["key"] == "business.sector":
        need.sector = value
    return Step(to="BUILD_PROFILE")


def _progress(ctx: Ctx, st: dict) -> dict:
    need = _need(ctx, st)
    remaining = len(customer_svc.missing_questions(ctx.db, need, uuid.UUID(st["customer_id"])))
    asked = st.get("profile_questions", 0) + 1  # this question included
    return {"asked": asked, "remaining": remaining}


def _parse_answer(q: dict, raw: str):
    t = q["type"]
    if t == "name":
        return parsing.parse_name(raw)
    if t == "nin":
        return parsing.parse_nin(raw)
    if t == "text":
        s = raw.strip()
        return s[:120] if 2 <= len(s) <= 120 else None
    if t == "sector":
        return raw if raw in UGANDA["sectors"] else parsing.parse_sector(raw)[0]
    if t == "district":
        return parsing.detect_district(raw)
    if t == "months":
        unit = "years" if q["key"] in ("business.age_months", "farm.operating_months", "employment.months") else "months"
        m = parsing.parse_months(raw, unit)
        return m if m is not None and 0 <= m <= 1200 else None
    if t == "money":
        v = parsing.parse_money_answer(raw)
        return int(v) if v is not None and v >= 0 else None
    if t == "yesno":
        return parsing.parse_yesno(raw)
    if t == "choice":
        r = raw.strip().lower()
        for val, lbl in q["options"]:
            if r in (val, lbl.lower()):
                return val
        return None
    return raw or None


def _help_for(q: dict) -> str:
    return {
        "name": "Please type your first and last name.",
        "nin": "That doesn't look like a NIN (14 characters, e.g. CM12345678ABCD). Reply 'skip' to continue without it.",
        "district": "I didn't recognise that district. Please type a district name, e.g. Kampala, Gulu or Mbarara.",
        "months": "Please answer with a period, e.g. '2 years' or '8 months'.",
        "money": "Please type an amount, e.g. '12 million' or 'UGX 800,000'. Reply 0 if none.",
        "yesno": "Please answer yes or no.", "sector": "Please choose one of the sectors.",
        "choice": "Please choose one of the options.",
    }.get(q["type"], "Sorry, I didn't understand. Please try again.")


def resolve_conflict(ctx: Ctx, st: dict, t: Trigger) -> Step:
    c = st["conflict"]
    field = c["key"].split(".")[-1].replace("_", " ")
    if t.kind == "ENTER":
        old, new = str(c["old"]), str(c["new"])
        ctx.say(f"Earlier we had '{old}' for {field}, and you just said '{new}'. Which is correct?",
                quick_replies=[qr(old[:20], "choose", "old"), qr(new[:20], "choose", "new")])
        return Step(wait=Wait(REPLY, DAY))
    choice = t.payload.get("value") or ("new" if _text(t) == str(c["new"]) else "old" if _text(t) == str(c["old"]) else None)
    if choice not in ("old", "new"):
        attempts = st.get("conflict_attempts", 0) + 1
        if attempts >= 2:
            from weza.domains.integrity.service import add_review
            add_review(ctx.db, "FACT_CONFLICT", f"Conflicting answers for {field}", "customer", st["customer_id"],
                       detail=c, due_hours=72)
            return Step(to="BUILD_PROFILE", patch={"conflict": None, "conflict_attempts": 0,
                                                   "skipped": [*(st.get("skipped") or []), c["key"]]})
        ctx.say("Please choose one of the two options.")
        return Step(wait=Wait(REPLY, DAY), patch={"conflict_attempts": attempts})
    value = c["new"] if choice == "new" else c["old"]
    customer_svc.upsert_fact(ctx.db, uuid.UUID(st["customer_id"]), c["key"], value, source="CUSTOMER",
                             channel=st.get("channel", "web"), confirmed=True, source_ref="conflict_resolution")
    return Step(to="BUILD_PROFILE", patch={"conflict": None, "conflict_attempts": 0})


def readiness_check(ctx: Ctx, st: dict, t: Trigger) -> Step:
    need = _need(ctx, st)
    if need.status in ("PROFILE_IN_PROGRESS", "PHONE_VERIFIED", "INTENT_CONFIRMED", "CUSTOMER_SELECTED",
                       "SUBMITTED", "TRACKING"):
        need.status = "READY_FOR_MATCHING"
    res = engine.match_need(ctx.db, need, trigger="journey")
    if res["readiness"] == "READY_NOW":
        return Step(to="PRESENT_OPTIONS")
    if res["readiness"] == "ALMOST_READY":
        return Step(to="REQUEST_MISSING_ITEM")
    return Step(to="OFFER_WAITING_ROOM")


def request_missing_item(ctx: Ctx, st: dict, t: Trigger) -> Step:
    need = _need(ctx, st)
    if t.kind == "ENTER":
        almost = ctx.db.execute(select(Match).where(Match.need_id == need.id, Match.state.in_(["RANKED", "PRESENTED"]),
                                                    Match.readiness == "ALMOST")).scalars().all()
        docs, other = {}, set()
        for m in almost:
            for o in m.explanation.get("outstanding", []):
                if o.get("doc_type"):
                    docs[o["doc_type"]] = o["text"].replace("Upload: ", "")
                else:
                    other.add(o["text"])
        items = [f"• {v}" for v in docs.values()] + [f"• {v}" for v in sorted(other)]
        ctx.say(f"You're almost there. To unlock {len(almost)} option{'s' if len(almost) != 1 else ''}, please "
                "provide:\n" + "\n".join(items),
                quick_replies=[qr("I've uploaded it", "uploaded"), qr("Show my options", "show"),
                               qr("Keep looking for me", "wait")])
        ctx.card("documents_needed", {"documents": [{"doc_type": k, "label": v} for k, v in docs.items()],
                                      "other": sorted(other)})
        return Step(wait=Wait(REPLY, 3 * DAY))
    a = _action(t)
    if a in ("uploaded", "document_uploaded"):
        n = st.get("missing_item_cycles", 0) + 1
        if n > 3:
            return Step(to="PRESENT_OPTIONS", patch={"missing_item_cycles": 0})
        return Step(to="READINESS_CHECK", patch={"missing_item_cycles": n})
    if a == "wait":
        return Step(to="OFFER_WAITING_ROOM")
    return Step(to="PRESENT_OPTIONS")


def offer_waiting_room(ctx: Ctx, st: dict, t: Trigger) -> Step:
    need = _need(ctx, st)
    if t.kind == "ENTER":
        excluded = ctx.db.execute(select(Match).where(Match.need_id == need.id, Match.state == "EXCLUDED")
                                  .order_by(Match.score.desc()).limit(5)).scalars().all()
        reasons = []
        for m in excluded:
            for r in m.explanation.get("excluded_by", []):
                if r["text"] not in reasons:
                    reasons.append(r["text"])
        msg = "No participating institution currently matches this request."
        if reasons:
            msg += " The main reasons right now:\n" + "\n".join(f"• {r}" for r in reasons[:3])
        msg += ("\n\nI can keep your request in the WEZA Waiting Room for 30 days and message you as soon as a "
                "suitable institution becomes available. Nothing is shared without your permission.")
        ctx.say(msg, quick_replies=[qr("Keep looking for me", "wait"), qr("Change my request", "change"),
                                    qr("No thanks", "no")])
        return Step(wait=Wait(REPLY, 7 * DAY))
    a = _action(t)
    if a == "wait" or (_text(t).lower().startswith("keep")):
        w = engine.opt_in_waiting(ctx.db, need)
        ctx.say(f"Done — you're in the Waiting Room until {w.expires_at:%d %b %Y}. I'll message you when a new "
                "option fits your need.")
        return Step(to="WAITING_ROOM")
    if a == "change":
        ctx.say("Tell me what you'd like to change — for example a different amount.")
        return Step(to="CONFIRM_INTENT_WAIT")
    return Step(to="SAVE_EXIT")


def confirm_intent_wait(ctx: Ctx, st: dict, t: Trigger) -> Step:
    if t.kind == "ENTER":
        return Step(wait=Wait(REPLY, DAY))
    return Step(to="REVISE_INTENT", patch={"last_text": _text(t)})


def waiting_room(ctx: Ctx, st: dict, t: Trigger) -> Step:
    if t.kind == "ENTER":
        return Step(wait=Wait(REPLY, 30 * DAY))
    a = _action(t)
    if a == "_market_match":
        ctx.say("Good news — a new option may fit your financing need. Take a look:")
        return Step(to="PRESENT_OPTIONS")
    if a == "leave":
        from weza.domains.matching.models import WaitingEntry
        w = ctx.db.get(WaitingEntry, uuid.UUID(st["need_id"]))
        if w:
            w.status = "LEFT"
        return Step(to="SAVE_EXIT")
    if a == "reconfirm":
        engine.opt_in_waiting(ctx.db, _need(ctx, st))
        ctx.say("Thanks — I'll keep looking for another 30 days.")
        return Step(wait=Wait(REPLY, 30 * DAY))
    ctx.say("I'm still looking for a suitable institution and will message you as soon as there's a match.",
            quick_replies=[qr("Leave the Waiting Room", "leave")])
    return Step(wait=Wait(REPLY, 30 * DAY))


def present_options(ctx: Ctx, st: dict, t: Trigger) -> Step:
    need = _need(ctx, st)
    matches = ctx.db.execute(select(Match).where(Match.need_id == need.id,
                                                 Match.state.in_(["RANKED", "PRESENTED", "SELECTED"]))
                             .order_by(Match.rank)).scalars().all()
    if t.kind == "ENTER":
        if not matches:
            return Step(to="READINESS_CHECK" if st.get("_rematched") is None else "OFFER_WAITING_ROOM",
                        patch={"_rematched": True})
        now = utcnow()
        for m in matches:
            if m.state == "RANKED":
                m.state, m.presented_at = "PRESENTED", now
        opts = engine.describe_options(ctx.db, matches)
        ready = [o for o in opts if o["readiness"] == "READY"]
        pref = ctx.db.get(Preference, uuid.UUID(st["customer_id"]))
        ctx.say(f"I found {len(opts)} option{'s' if len(opts) != 1 else ''} that fit your need. The match shows how "
                "well your request fits each institution's current criteria — it is not a loan approval.",
                quick_replies=[qr(f"Choose {o['institution']}", "select", o["match_id"]) for o in ready[:3]]
                + [qr("Change preferences", "prefs"), qr("Keep looking", "wait")])
        ctx.card("options", {"options": opts, "preferences": list(pref.ranking) if pref else [],
                             "preference_choices": RANKING_PREFS})
        emit(ctx.db, "MatchesPresented", topic="matching", aggregate_type="need", aggregate_id=need.id,
             data={"count": len(opts)})
        return Step(wait=Wait(REPLY, 7 * DAY), patch={"_rematched": None})
    a = _action(t)
    if a == "select" or _text(t).isdigit():
        mid = t.payload.get("value")
        if not mid and _text(t).isdigit():
            idx = int(_text(t)) - 1
            mid = str(matches[idx].id) if 0 <= idx < len(matches) else None
        m = next((x for x in matches if str(x.id) == mid), None)
        if m is None:
            ctx.say("Please choose one of the options shown.")
            return Step(wait=Wait(REPLY, 7 * DAY))
        if m.readiness != "READY":
            ctx.say("That option needs a few more details first: " + "; ".join(
                o["text"] for o in m.explanation.get("outstanding", [])))
            return Step(wait=Wait(REPLY, 7 * DAY))
        m.state, m.selected_at = "SELECTED", utcnow()
        need.status = "CUSTOMER_SELECTED"
        emit(ctx.db, "MatchSelected", topic="matching", aggregate_type="need", aggregate_id=need.id,
             institution_id=m.institution_id, data={"match_id": str(m.id)})
        return Step(to="CONSENT", patch={"selected_match_id": str(m.id)})
    if a == "prefs":
        values = t.payload.get("values")
        if values is not None:
            pref = ctx.db.get(Preference, uuid.UUID(st["customer_id"]))
            pref.ranking = [v for v in values if v in RANKING_PREFS]
            return Step(to="RERANK")
        ctx.say("What matters most to you? Choose one, or type several separated by commas.",
                quick_replies=[qr(lbl, "pref", code) for code, lbl in RANKING_PREFS.items()])
        return Step(wait=Wait(REPLY, 7 * DAY))
    if a == "pref":
        pref = ctx.db.get(Preference, uuid.UUID(st["customer_id"]))
        pref.ranking = [t.payload.get("value")] if t.payload.get("value") in RANKING_PREFS else []
        return Step(to="RERANK")
    if a == "wait":
        return Step(to="OFFER_WAITING_ROOM")
    if a == "why_not":
        excluded = ctx.db.execute(select(Match).where(Match.need_id == need.id, Match.state == "EXCLUDED")).scalars().all()
        lines = []
        for m in excluded[:5]:
            inst = ctx.db.get(Institution, m.institution_id)
            reason = (m.explanation.get("excluded_by") or [{"text": "Below the minimum match"}])[0]["text"]
            lines.append(f"• {inst.display_name}: {reason}")
        ctx.say("Why some institutions aren't shown:\n" + ("\n".join(lines) if lines else "• No other active options."))
        return Step(wait=Wait(REPLY, 7 * DAY))
    ctx.say("Choose an option to continue, or tap 'Keep looking'.")
    return Step(wait=Wait(REPLY, 7 * DAY))


def rerank(ctx: Ctx, st: dict, t: Trigger) -> Step:
    engine.match_need(ctx.db, _need(ctx, st), trigger="preferences")
    return Step(to="PRESENT_OPTIONS")


def consent_node(ctx: Ctx, st: dict, t: Trigger) -> Step:
    m = ctx.db.get(Match, uuid.UUID(st["selected_match_id"]))
    inst = ctx.db.get(Institution, m.institution_id)
    if t.kind == "ENTER":
        tpl = consent_svc.current_template(ctx.db)
        rendered = consent_svc.render(tpl, inst.display_name)
        ctx.card("consent", {**rendered, "match_id": str(m.id), "institution": inst.display_name,
                             "option": engine.describe_options(ctx.db, [m])[0]})
        ctx.say(f"Before I share your request with {inst.display_name}, please review exactly what will be shared.",
                quick_replies=[qr(f"I agree — share with {inst.display_name}"[:40], "agree", str(tpl.id)),
                               qr("Not now", "decline")])
        return Step(wait=Wait(REPLY, DAY), patch={"consent_template_id": str(tpl.id)})
    a = _action(t)
    if a == "agree":
        need = _need(ctx, st)
        pref = ctx.db.get(Preference, uuid.UUID(st["customer_id"]))
        c = consent_svc.grant(ctx.db, _customer_actor(st), customer_id=need.customer_id, institution_id=inst.id,
                              need_id=need.id, match_id=m.id,
                              template_id=uuid.UUID(t.payload.get("value") or st["consent_template_id"]),
                              categories=t.payload.get("categories"), channel=st.get("channel", "web"),
                              contact_channel=t.payload.get("contact_channel") or ("whatsapp" if st.get("channel") == "whatsapp" else (
                                  pref.contact_channel if pref else "phone")),
                              contact_window=t.payload.get("contact_window") or (pref.contact_window if pref else "ANY"))
        need.status = "CONSENTED"
        nxt = "CRB_CHECK" if _crb_check_due(ctx, st, inst.id) else "CREATE_OPPORTUNITY"
        return Step(to=nxt, patch={"consent_id": str(c.id)})
    if a == "decline":
        m.state = "PRESENTED"
        _need(ctx, st).status = "MATCHED"
        emit(ctx.db, "ConsentDeclined", topic="opportunity", aggregate_type="match", aggregate_id=m.id,
             institution_id=inst.id, data={})
        ctx.say("No problem — nothing has been shared.")
        return Step(to="PRESENT_OPTIONS")
    ctx.say("Please choose 'I agree' to share, or 'Not now'.")
    return Step(wait=Wait(REPLY, DAY))


def _crb_check_due(ctx: Ctx, st: dict, institution_id: uuid.UUID) -> bool:
    """Ask for the Just-In-Time bureau check only when it's enabled, the customer gave a NIN, and no result for this
    lender can be reused (so nobody is asked, or charged, twice)."""
    from weza.config import get_settings
    from weza.domains.consent import crb_service
    if not get_settings().crb_enabled:
        return False
    cust_id = uuid.UUID(st["customer_id"])
    customer = ctx.db.get(Customer, cust_id)
    if not identity.vault_read(ctx.db, customer.vault_token).get("nin"):
        return False
    return crb_service.reusable(ctx.db, cust_id, institution_id) is None


def crb_check(ctx: Ctx, st: dict, t: Trigger) -> Step:
    """Credit bureau check for the lender the customer just agreed to share with (explicit, separate consent).
    Outcomes come only from crb_service (deterministic); a bureau problem never stops the request."""
    from weza.domains.consent import crb_service
    m = ctx.db.get(Match, uuid.UUID(st["selected_match_id"]))
    inst = ctx.db.get(Institution, m.institution_id)
    if t.kind == "ENTER":
        ctx.say(crb_service.consent_text(inst.display_name),
                quick_replies=[qr("Yes, check", "crb_consent", "yes"), qr("No, skip", "crb_consent", "no")])
        return Step(wait=Wait(REPLY, DAY))
    value, low = str(t.payload.get("value") or ""), _text(t).lower()
    yes = value == "yes" or low in ("yes", "y", "ok", "okay", "agree", "i agree", "yes, check")
    no = value == "no" or low in ("no", "n", "skip", "no thanks", "no, skip")
    if not (yes or no) and not st.get("crb_challenge_id"):
        ctx.say("Please reply Yes to run the credit bureau check, or No to skip it.",
                quick_replies=[qr("Yes, check", "crb_consent", "yes"), qr("No, skip", "crb_consent", "no")])
        return Step(wait=Wait(REPLY, DAY))
    if no:
        audit(ctx.db, _customer_actor(st), "GNGRID_CRB_CHECK_DECLINED", "match", m.id, institution_id=inst.id)
        return Step(to="CREATE_OPPORTUNITY")
    if not st.get("crb_challenge_id") and crb_service.reusable(ctx.db, _customer_actor(st).id, inst.id) is None:
        challenge = crb_service.issue_consent_otp(ctx.db, _customer_actor(st), inst.id,
                                                  channel=st.get("channel", "web"))
        ctx.say(f"Enter the 10-digit WEZA consent code sent to {challenge['masked']} to authorise "
                f"the credit bureau check for {inst.display_name}.")
        ctx.card("otp_input", {**challenge, "challenge_id": str(challenge["challenge_id"]),
                               "selected_institution_id": str(inst.id),
                               "expires_at": challenge["expires_at"].isoformat(), "purpose": "crb"})
        return Step(wait=Wait(REPLY, DAY), patch={"crb_challenge_id": str(challenge["challenge_id"])})
    try:
        res = crb_service.run_check(ctx.db, _customer_actor(st), inst.id, channel=st.get("channel", "web"),
            challenge_id=uuid.UUID(st["crb_challenge_id"]) if st.get("crb_challenge_id") else None,
            otp=_text(t).replace(" ", ""))
    except ValidationFailed as exc:
        ctx.say(exc.message)
        patch = {"crb_challenge_id": None} if exc.code in ("OTP_LOCKED", "OTP_EXPIRED") else {}
        return Step(wait=Wait(REPLY, DAY), patch=patch)
    if res["status"] == "VERIFIED":
        ctx.say(f"Thank you — your National ID details match the credit bureau record. {inst.display_name} will see "
                "a summary of your credit history.")
    elif res["status"] not in crb_service.FAILED:  # identity failures are explained when sharing is refused
        ctx.say(f"The credit bureau check couldn't be completed right now. Your request continues — "
                f"{inst.display_name} will do its own checks.")
    return Step(to="CREATE_OPPORTUNITY", patch={"crb_challenge_id": None})


def create_opportunity(ctx: Ctx, st: dict, t: Trigger) -> Step:
    from weza.domains.consent.models import Consent
    need = _need(ctx, st)
    m = ctx.db.get(Match, uuid.UUID(st["selected_match_id"]))
    c = ctx.db.get(Consent, uuid.UUID(st["consent_id"]))
    try:
        opp = opp_svc.qualify(ctx.db, _customer_actor(st), need, m, c)
    except opp_svc.RematchRequired:
        ctx.say("That option changed just now, so nothing was shared. Let me refresh your options.")
        return Step(to="READINESS_CHECK", patch={"selected_match_id": None})
    except ValidationFailed as exc:
        ctx.say(exc.message)
        return Step(to="PRESENT_OPTIONS")
    ids = [*(st.get("opportunity_ids") or []), str(opp.id)]
    ctx.instance.opportunity_id = opp.id
    if opp.state == "QUALIFIED" and opp.integrity_hold:
        ctx.say("Thank you. We're completing a few routine checks before sharing your request. We'll update you "
                "shortly.")
        return Step(to="TRACKING", patch={"opportunity_ids": ids})
    if opp.state == "ROUTING_FAILED":
        ctx.say("That institution isn't available right now, so nothing was shared. Let me refresh your options.")
        return Step(to="READINESS_CHECK", patch={"opportunity_ids": ids})
    return Step(to="CONFIRM", patch={"opportunity_ids": ids})


def confirm(ctx: Ctx, st: dict, t: Trigger) -> Step:
    opp = ctx.db.get(Opportunity, uuid.UUID(st["opportunity_ids"][-1]))
    inst = ctx.db.get(Institution, opp.institution_id)
    stg = ctx.db.get(ServiceTarget, inst.id)
    hours = round((stg.first_contact_within_minutes if stg else 1440) / 60)
    ctx.card("submitted", {"reference": opp.reference, "institution": inst.display_name,
                           "expected_contact_hours": hours, "opportunity_id": str(opp.id)})
    ctx.say(f"Done! Your request {opp.reference} has been shared with {inst.display_name}. They aim to contact you "
            f"within {hours} hours. {inst.display_name} will do its own checks and make the decision — WEZA will keep "
            "you updated here.", quick_replies=[qr("Track my request", "status")])
    return Step(to="TRACKING")


def tracking(ctx: Ctx, st: dict, t: Trigger) -> Step:
    if t.kind == "ENTER":
        return Step(wait=Wait(REPLY, 90 * DAY))
    a = _action(t)
    if a == "_declined":
        return Step(to="RESCUE_ASK", patch={"declined_opportunity_id": t.payload.get("value"),
                                            "decline_reason": t.payload.get("reason")})
    if a == "another":
        return Step(to="PRESENT_OPTIONS")
    lines = []
    for oid in st.get("opportunity_ids") or []:
        o = ctx.db.get(Opportunity, uuid.UUID(oid))
        inst = ctx.db.get(Institution, o.institution_id)
        lines.append(f"• {o.reference} with {inst.display_name}: {status_label(o.state)}")
    ctx.say("Here's where things stand:\n" + ("\n".join(lines) if lines else "• Nothing submitted yet."),
            quick_replies=[qr("Refresh status", "status")])
    return Step(wait=Wait(REPLY, 90 * DAY))


def handle_consent_withdrawal(db, customer_id: uuid.UUID) -> list[dict]:
    """An explicit stop command takes precedence over an outstanding information request."""
    from weza.domains.consent.models import Consent
    actor = Actor(kind="CUSTOMER", id=customer_id)
    records = db.execute(select(Consent).where(Consent.customer_id == customer_id,
                                               Consent.status == "GRANTED").with_for_update()).scalars().all()
    for consent in records:
        consent_svc.withdraw(db, actor, consent.id, customer_id, "Customer withdrew through WhatsApp")
        if consent.opportunity_id:
            opp = db.execute(select(Opportunity).where(Opportunity.id == consent.opportunity_id,
                Opportunity.customer_id == customer_id, Opportunity.institution_id == consent.institution_id)
                .with_for_update()).scalar_one_or_none()
            if opp:
                opp_svc.close_open_info_requests(db, opp, "Consent withdrawn")
                if opp.state not in (*opp_svc.TERMINAL, "REPORTED_DISBURSED"):
                    opp_svc.customer_withdraw(db, actor, opp)
    return [{"type": "text", "text": "Your consent has been withdrawn. Institutions can no longer access "
             "your shared details through WEZA." if records else "You have no active sharing consent to withdraw."}]


def fulfil_info(db, customer_id: uuid.UUID, *, text: str | None = None,
                document_id: uuid.UUID | None = None, doc_type: str | None = None) -> list[dict] | None:
    """Route a reply to the customer's oldest active request; checked documents use the same mutation service."""
    from weza.domains.consent.models import Consent
    from weza.domains.opportunity.models import InfoRequest
    query = select(InfoRequest).join(Opportunity, Opportunity.id == InfoRequest.opportunity_id).join(
        Consent, Consent.id == Opportunity.consent_id).where(InfoRequest.customer_id == customer_id,
        Opportunity.customer_id == customer_id, InfoRequest.institution_id == Opportunity.institution_id,
        Consent.customer_id == customer_id, Consent.institution_id == Opportunity.institution_id,
        Consent.status == "GRANTED", InfoRequest.status == "OPEN", Opportunity.state.in_(opp_svc.OPEN_STATES))
    if document_id:
        query = query.where(InfoRequest.kind == "DOCUMENT", InfoRequest.doc_type == doc_type)
    request = db.execute(query.order_by(InfoRequest.created_at, InfoRequest.id).limit(1)
                         .with_for_update(of=InfoRequest)).scalar_one_or_none()
    if request is None:
        return None
    if request.kind == "DOCUMENT" and not document_id:
        return [{"type": "text", "text": "Please send the requested document as a PDF, JPG or PNG in this chat: "
                 + request.message}]
    try:
        opp_svc.fulfil_info_request(db, Actor(kind="CUSTOMER", id=customer_id), request,
                                    response_text=text, document_id=document_id)
    except ValidationFailed as exc:
        return [{"type": "text", "text": exc.message}]
    return [{"type": "text", "text": "Thank you. Your response has been sent to the institution."}]


def status_label(state: str) -> str:
    return {"QUALIFIED": "Completing checks", "ROUTED": "Shared — waiting for the institution",
            "RECEIVED": "Opened by the institution", "ASSIGNED": "Assigned to an officer",
            "CONTACTED": "The institution has contacted you", "PROCEEDING": "In the institution's process",
            "SUBMITTED_TO_INSTITUTION": "Application submitted to the institution",
            "REPORTED_APPROVED": "Reported approved by the institution",
            "REPORTED_DISBURSED": "Reported disbursed by the institution",
            "REPORTED_DECLINED": "Reported declined by the institution", "REMATCH_ELIGIBLE": "Looking for alternatives",
            "WITHDRAWN": "Withdrawn", "EXPIRED": "Expired", "CLOSED": "Closed",
            "ROUTING_FAILED": "Not shared — institution unavailable"}.get(state, state.title())


def rescue_ask(ctx: Ctx, st: dict, t: Trigger) -> Step:
    opp = ctx.db.get(Opportunity, uuid.UUID(st["declined_opportunity_id"]))
    inst = ctx.db.get(Institution, opp.institution_id)
    if t.kind == "ENTER":
        ctx.say(f"{inst.display_name} has reported that it can't proceed with your request {opp.reference}. Would "
                "you like WEZA to check other institutions? Nothing will be shared without your permission.",
                quick_replies=[qr("Yes, check alternatives", "rescue_yes"), qr("No, close my request", "rescue_no")])
        return Step(wait=Wait(REPLY, 7 * DAY))
    if _action(t) == "rescue_yes":
        if opp.state == "REPORTED_DECLINED":
            opp_svc.OPP_SM.check(opp.state, "REMATCH_ELIGIBLE")
            opp.state = "REMATCH_ELIGIBLE"
        need = _need(ctx, st)
        need.status = "READY_FOR_MATCHING"
        emit(ctx.db, "RescueRequested", topic="opportunity", aggregate_type="need", aggregate_id=need.id, data={})
        return Step(to="READINESS_CHECK")
    return Step(to="CLOSE_NEED")


def close_need(ctx: Ctx, st: dict, t: Trigger) -> Step:
    need = _need(ctx, st)
    if need.status not in ("SUBMITTED", "TRACKING"):
        need.status = "CLOSED"
    else:
        need.status = "CLOSED"
    emit(ctx.db, "NeedClosed", topic="customer", aggregate_type="need", aggregate_id=need.id, data={})
    ctx.say("Your request is closed. You can start a new one with WEZA any time.")
    return Step(terminal="COMPLETED")


def save_exit(ctx: Ctx, st: dict, t: Trigger) -> Step:
    if t.kind == "ENTER":
        ctx.say("Your progress is saved. Reply any time to continue.")
        return Step(wait=Wait(REPLY, 14 * DAY))
    if st.get("customer_id") and _need(ctx, st).intent_confirmed_at:
        return Step(to="BUILD_PROFILE", patch={"skipped": []})
    return Step(to="UNDERSTAND_INTENT", patch={"last_text": _text(t), "intent_turns": 0})


def remind(ctx: Ctx, st: dict, t: Trigger) -> Step:
    n = st.get("reminders", 0) + 1
    if n > 2:
        return Step(to="EXPIRE", patch={"reminders": n})
    if st.get("customer_id"):
        from weza.domains.notification.service import notify_customer
        notify_customer(ctx.db, uuid.UUID(st["customer_id"]), "JourneyReminder", title="Continue your WEZA request",
                        body="Your financing request is waiting for you. Reply to continue where you left off.",
                        link="/start")
    return Step(to=st.get("_wait_node") or "GREET", patch={"reminders": n})


def expire(ctx: Ctx, st: dict, t: Trigger) -> Step:
    need = _need(ctx, st)
    if need.status not in ("SUBMITTED", "TRACKING", "CLOSED"):
        need.status = "EXPIRED"
    from weza.domains.matching.models import WaitingEntry
    w = ctx.db.get(WaitingEntry, need.id)
    if w and w.status in ("OPTED_IN", "RECONFIRM_DUE"):
        w.status = "EXPIRED"
    emit(ctx.db, "JourneyExpired", topic="customer", aggregate_type="need", aggregate_id=need.id, data={})
    return Step(terminal="EXPIRED")


def complete(ctx: Ctx, st: dict, t: Trigger) -> Step:
    return Step(terminal="COMPLETED")


R = "REMIND"
GRAPH = register(GraphDef(type="customer_journey", version=1, start="GREET", nodes={
    "GREET": Node(greet, 2, R), "UNDERSTAND_INTENT": Node(understand_intent, 1),
    "ASK_INTENT": Node(ask_intent, 2, R), "CONFIRM_INTENT": Node(confirm_intent, 0, R),
    "REVISE_INTENT": Node(revise_intent, 1), "CONFIRM_INTENT_WAIT": Node(confirm_intent_wait, 0, R),
    "VERIFY_PHONE": Node(verify_phone, 2, R), "BUILD_PROFILE": Node(build_profile, 2),
    "ASK_PROFILE": Node(ask_profile, 2, R), "RESOLVE_CONFLICT": Node(resolve_conflict, 0, R),
    "READINESS_CHECK": Node(readiness_check, 2), "REQUEST_MISSING_ITEM": Node(request_missing_item, 2, R),
    "OFFER_WAITING_ROOM": Node(offer_waiting_room, 0, "SAVE_EXIT"), "WAITING_ROOM": Node(waiting_room, 3, "EXPIRE"),
    "PRESENT_OPTIONS": Node(present_options, 0, R), "RERANK": Node(rerank, 2), "CONSENT": Node(consent_node, 0, R),
    "CRB_CHECK": Node(crb_check, 1, R),
    "CREATE_OPPORTUNITY": Node(create_opportunity, 2), "CONFIRM": Node(confirm, 2),
    "TRACKING": Node(tracking, 2, "COMPLETE"), "RESCUE_ASK": Node(rescue_ask, 0, "CLOSE_NEED"),
    "CLOSE_NEED": Node(close_need, 2), "SAVE_EXIT": Node(save_exit, 2, "EXPIRE"), "REMIND": Node(remind, 2),
    "EXPIRE": Node(expire, 2), "COMPLETE": Node(complete, 2),
}))


def format_for_channel(outputs: list[dict]) -> list[dict]:
    """Strip ephemeral/secret content before persisting outbound messages (session tokens, dev OTP codes)."""
    safe = []
    for o in outputs:
        if o.get("ephemeral"):
            continue
        if o.get("type") == "card" and o.get("card") == "session":
            continue
        if o.get("type") == "card" and o.get("card") == "otp_input":
            o = {**o, "data": {k: v for k, v in o["data"].items() if k != "dev_code"}}
        safe.append(o)
    return safe


def whatsapp_text(o: dict) -> str | None:
    """Render a graph output as WhatsApp text (cards become concise summaries)."""
    if o.get("type") == "text":
        return o["text"] + (f"\n_{o['hint']}_" if o.get("hint") else "")
    card, d = o.get("card"), o.get("data") or {}
    if card == "understanding":
        parts = [f"*Amount:* {d.get('amount')}", f"*Purpose:* {d.get('purpose')}",
                 f"*You are:* {d.get('customer_type')}"]
        if d.get("sector"):
            parts.append(f"*Sector:* {d['sector']}")
        return "\n".join(parts)
    if card == "options":
        lines = []
        for i, op in enumerate(d.get("options", []), start=1):
            lines.append(f"*{i}. {op['institution']}* — {op['product']} (match {op['score']})\n"
                         f"{op['amount_range']} · {op['tenor']}\nWhy: {', '.join(op['why'][:3])}"
                         + ("" if op["readiness"] == "READY" else f"\nNeeds: {'; '.join(op['outstanding'])}"))
        return "\n\n".join(lines) + "\n\nReply with the option number to choose."
    if card == "consent":
        cats = "\n".join(f"• {c['label']}" for c in d.get("categories", []))
        return f"*{d.get('title')}*\n\n{d.get('text')}\n\n*Shared:*\n{cats}\n\nConsent version {d.get('version')}"
    if card == "submitted":
        return f"Reference: *{d.get('reference')}*"
    if card == "otp_input" and d.get("dev_code"):
        return f"(Test mode) Your code is {d['dev_code']}"
    if card == "documents_needed":
        return "Please send each document right here in this chat as a clear photo or PDF (up to 10 MB)."
    return None


def fmt_field(field: str, v) -> str:
    return fmt(field, v)


_ = timedelta  # keep import for future timer helpers
