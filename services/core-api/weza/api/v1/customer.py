"""Authenticated customer endpoints (/me): profile with provenance, needs & status tracking, preferences,
documents, consents and withdrawal (FSD §8, §13, BRD §33)."""

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.api.deps import DB, customer_actor
from weza.domains.consent import service as consent_svc
from weza.domains.consent.models import Consent
from weza.domains.customer import documents as docs
from weza.domains.customer import service as customer_svc
from weza.domains.customer.models import Customer, Document, Preference
from weza.domains.identity.service import mask_phone, vault_read
from weza.domains.institution.models import Institution
from weza.domains.matching import engine
from weza.domains.matching.models import Match, WaitingEntry
from weza.domains.misc_models import Notification
from weza.domains.need import journey
from weza.domains.need.models import FinancialNeed
from weza.domains.need.service import journey_token, need_summary
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import Opportunity, Outcome
from weza.domains.verification import service as verification
from weza.platform.context import Actor
from weza.platform.db import utcnow
from weza.platform.errors import NotFound, ValidationFailed
from weza.platform.models import GraphInstance

router = APIRouter(prefix="/me", tags=["customer"])
FIELD_LABELS = customer_svc.FIELD_LABELS
EDITABLE = customer_svc.EDITABLE


def _need_owned(db: Session, actor: Actor, need_id: uuid.UUID) -> FinancialNeed:
    n = db.get(FinancialNeed, need_id)
    if n is None or n.customer_id != actor.id:
        raise NotFound("Not found.")
    return n


@router.get("/profile")
def profile(actor: Actor = Depends(customer_actor), db: Session = DB):
    cust = db.get(Customer, actor.id)
    vault = vault_read(db, cust.vault_token)
    facts = customer_svc.current_facts(db, actor.id)
    pref = db.get(Preference, actor.id)
    return {
        "identity": verification.summary(db, actor.id),
        "customer": {"id": str(cust.id), "customer_type": cust.customer_type, "verification_level": cust.verification_level,
                     "phone": mask_phone(vault.get("phone")), "name": vault.get("full_name")},
        "facts": [{"key": k, "label": FIELD_LABELS.get(k, k), "value": f.value.get("v"), "source": f.source,
                   "channel": f.source_channel, "state": f.verification_state, "captured_at": f.captured_at.isoformat(),
                   "editable": k in EDITABLE, "stale": not customer_svc.is_fresh(f)} for k, f in sorted(facts.items())],
        "preferences": {"contact_channel": pref.contact_channel if pref else "phone",
                        "contact_window": pref.contact_window if pref else "ANY",
                        "ranking": list(pref.ranking) if pref else []},
    }


class IdentityIn(BaseModel):
    nin: str | None = Field(None, max_length=20)
    full_name: str | None = Field(None, max_length=120)


@router.put("/identity")
def correct_identity(body: IdentityIn, actor: Actor = Depends(customer_actor), db: Session = DB):
    """Correct the National ID number and/or name; a changed value is re-checked against the registry."""
    from weza.domains.intelligence.parsing import parse_name, parse_nin
    if not (body.nin or body.full_name):
        raise ValidationFailed("Enter your National ID number or full name.")
    if body.nin:
        nin = parse_nin(body.nin)
        if not nin:
            raise ValidationFailed("That doesn't look like a Ugandan National ID number (14 characters, e.g. "
                                   "CM12345678ABCD).", code="INVALID_NIN")
        customer_svc.upsert_fact(db, actor.id, "identity.nin", nin, source="CUSTOMER", channel="web", confirmed=True,
                                 source_ref="identity_correction")
    if body.full_name:
        name = parse_name(body.full_name)
        if not name:
            raise ValidationFailed("Please enter your first and last name.", code="INVALID_NAME")
        customer_svc.upsert_fact(db, actor.id, "identity.full_name", name, source="CUSTOMER", channel="web",
                                 confirmed=True, source_ref="identity_correction")
    return profile(actor, db)


class FactPatch(BaseModel):
    key: str
    value: str | int | float | bool


@router.patch("/profile")
def correct_fact(body: FactPatch, actor: Actor = Depends(customer_actor), db: Session = DB):
    """FSD-PRO-002: customer corrections; material changes re-run matching via MaterialFactChanged."""
    if body.key not in EDITABLE:
        raise ValidationFailed("This field can't be edited here.")
    value, hint = customer_svc.parse_fact_value(body.key, str(body.value))
    if value is None:
        raise ValidationFailed(hint or "Invalid value.")
    customer_svc.upsert_fact(db, actor.id, body.key, value, source="CUSTOMER", channel="web", confirmed=True,
                             source_ref="profile_correction")
    return profile(actor, db)


class PrefsIn(BaseModel):
    contact_channel: str = Field("phone", pattern="^(phone|sms|whatsapp)$")
    contact_window: str = Field("ANY", max_length=40)
    ranking: list[str] = []


@router.put("/preferences")
def set_prefs(body: PrefsIn, actor: Actor = Depends(customer_actor), db: Session = DB):
    pref = db.get(Preference, actor.id) or Preference(customer_id=actor.id)
    pref.contact_channel, pref.contact_window = body.contact_channel, body.contact_window
    pref.ranking = [r for r in body.ranking if r in journey.RANKING_PREFS]
    db.merge(pref)
    return {"ok": True}


@router.get("/needs")
def needs(actor: Actor = Depends(customer_actor), db: Session = DB):
    out = []
    for n in db.execute(select(FinancialNeed).where(FinancialNeed.customer_id == actor.id)
                        .order_by(FinancialNeed.created_at.desc())).scalars():
        opps = db.execute(select(Opportunity).where(Opportunity.need_id == n.id).order_by(Opportunity.qualified_at)).scalars()
        gi = db.get(GraphInstance, n.journey_id) if n.journey_id else None
        out.append({**need_summary(n), "journey": {"id": str(gi.id), "node": gi.current_node, "status": gi.status,
                                                   "token": journey_token(gi.id)} if gi else None,
                    "opportunities": [_opp_for_customer(db, o) for o in opps],
                    "waiting": _waiting(db, n.id)})
    return {"needs": out}


def _waiting(db: Session, need_id) -> dict | None:
    w = db.get(WaitingEntry, need_id)
    return {"status": w.status, "expires_at": w.expires_at.isoformat(), "renewals": w.renewals} if w else None


def _opp_for_customer(db: Session, o: Opportunity) -> dict:
    inst = db.get(Institution, o.institution_id)
    c = db.get(Consent, o.consent_id)
    outs = db.execute(select(Outcome).where(Outcome.opportunity_id == o.id).order_by(Outcome.reported_at)).scalars()
    from weza.domains.opportunity.models import Activity
    timeline = [{"state": a.kind, "label": journey.status_label(a.kind), "at": a.at.isoformat()} for a in
                db.execute(select(Activity).where(Activity.opportunity_id == o.id).order_by(Activity.at)).scalars()
                if a.kind in ("QUALIFIED", "ROUTED", "ASSIGNED", "CONTACTED", "PROCEEDING", "SUBMITTED_TO_INSTITUTION",
                              "REPORTED_APPROVED", "REPORTED_DECLINED", "REPORTED_DISBURSED", "WITHDRAWN", "EXPIRED")]
    return {"id": str(o.id), "reference": o.reference, "institution": inst.display_name, "state": o.state,
            "status_label": journey.status_label(o.state), "amount": float(o.amount),
            "product": (o.snapshot.get("product_version") or {}).get("name"), "qualified_at": o.qualified_at.isoformat(),
            "consent": {"id": str(c.id), "status": c.status, "categories": c.data_categories,
                        "version": c.template_version} if c else None,
            "outcomes": [{"state": x.state, "label": journey.status_label(x.state),
                          "approved_amount": float(x.approved_amount) if x.approved_amount else None,
                          "disbursed_amount": float(x.disbursed_amount) if x.disbursed_amount else None,
                          "reported_at": x.reported_at.isoformat(), "reported_by": inst.display_name,
                          "terms": opp_svc.outcome_terms(x)} for x in outs],
            "info_requests": opp_svc.info_requests(db, o.id, include_responses=True),
            "timeline": timeline, "can_withdraw": o.state not in opp_svc.TERMINAL | {"REPORTED_DISBURSED", "REPORTED_DECLINED",
                                                                                     "REMATCH_ELIGIBLE"}}


@router.get("/needs/{need_id}/matches")
def matches(need_id: uuid.UUID, actor: Actor = Depends(customer_actor), db: Session = DB):
    n = _need_owned(db, actor, need_id)
    ms = db.execute(select(Match).where(Match.need_id == n.id, Match.state.in_(["RANKED", "PRESENTED", "SELECTED"]))
                    .order_by(Match.rank)).scalars().all()
    excluded = db.execute(select(Match).where(Match.need_id == n.id, Match.state == "EXCLUDED")).scalars().all()
    why_not = []
    for m in excluded:
        inst = db.get(Institution, m.institution_id)
        why_not.append({"institution": inst.display_name, "reasons": [r["text"] for r in m.explanation.get("excluded_by", [])]
                        or [f"Match below this institution's minimum ({round(m.score)})"]})
    return {"need": need_summary(n), "options": engine.describe_options(db, ms), "why_not": why_not,
            "disclaimer": "A match shows how well your request fits an institution's current criteria. It is not a "
                          "loan approval; the institution makes its own decision."}


@router.post("/opportunities/{opp_id}/withdraw")
def withdraw(opp_id: uuid.UUID, actor: Actor = Depends(customer_actor), db: Session = DB):
    o = db.get(Opportunity, opp_id)
    if o is None or o.customer_id != actor.id:
        raise NotFound("Not found.")
    opp_svc.customer_withdraw(db, actor, o)
    c = db.get(Consent, o.consent_id)
    if c and c.status == "GRANTED":
        consent_svc.withdraw(db, actor, c.id, actor.id, "Request withdrawn by customer")
    return _opp_for_customer(db, o)


@router.get("/info-requests")
def my_info_requests(actor: Actor = Depends(customer_actor), db: Session = DB):
    """Everything institutions have asked this customer for, open first."""
    out = []
    for o in db.execute(select(Opportunity).where(Opportunity.customer_id == actor.id)).scalars():
        inst = db.get(Institution, o.institution_id)
        for r in opp_svc.info_requests(db, o.id, include_responses=True):
            out.append({**r, "opportunity_id": str(o.id), "reference": o.reference, "institution": inst.display_name})
    out.sort(key=lambda r: (r["status"] != "OPEN", r["created_at"]))
    return {"requests": out, "open": sum(1 for r in out if r["status"] == "OPEN"), "doc_types": docs.DOC_TYPES,
            "note": "Answering is your choice. WEZA and institutions will never ask for your PIN, password or "
                    "one-time codes."}


class InfoResponseIn(BaseModel):
    response_text: str | None = Field(None, max_length=2000)
    document_id: str | None = None


@router.post("/info-requests/{request_id}/fulfil")
@router.post("/info-requests/{request_id}/respond")
def respond_info_request(request_id: uuid.UUID, body: InfoResponseIn, actor: Actor = Depends(customer_actor),
                         db: Session = DB):
    from weza.domains.opportunity.models import InfoRequest
    r = db.get(InfoRequest, request_id)
    if r is None or r.customer_id != actor.id:
        raise NotFound("Not found.")
    opp_svc.fulfil_info_request(db, actor, r, response_text=body.response_text,
                                document_id=uuid.UUID(body.document_id) if body.document_id else None)
    return my_info_requests(actor, db)


@router.get("/consents")
def consents(actor: Actor = Depends(customer_actor), db: Session = DB):
    out = []
    for c in db.execute(select(Consent).where(Consent.customer_id == actor.id).order_by(Consent.granted_at.desc())).scalars():
        inst = db.get(Institution, c.institution_id)
        out.append({"id": str(c.id), "institution": inst.display_name, "status": c.status,
                    "categories": [consent_svc.CATEGORY_LABELS.get(x, x) for x in c.data_categories],
                    "version": c.template_version, "granted_at": c.granted_at.isoformat(),
                    "withdrawn_at": c.withdrawn_at.isoformat() if c.withdrawn_at else None})
    return {"consents": out, "note": "Withdrawing stops future sharing by WEZA. It cannot remove information an "
                                     "institution has already lawfully received."}


@router.post("/consents/{consent_id}/withdraw")
def withdraw_consent(consent_id: uuid.UUID, actor: Actor = Depends(customer_actor), db: Session = DB):
    consent_svc.withdraw(db, actor, consent_id, actor.id, "Withdrawn by customer")
    return consents(actor, db)


class WaitingIn(BaseModel):
    action: str = Field(..., pattern="^(opt_in|reconfirm|leave)$")


@router.post("/needs/{need_id}/waiting-room")
def waiting_room(need_id: uuid.UUID, body: WaitingIn, actor: Actor = Depends(customer_actor), db: Session = DB):
    n = _need_owned(db, actor, need_id)
    if body.action in ("opt_in", "reconfirm"):
        w = engine.opt_in_waiting(db, n)
        if body.action == "reconfirm":
            w.renewals += 1
            if w.renewals > 3:
                raise ValidationFailed("The Waiting Room can be renewed up to 3 times. Please start a new request.")
    else:
        w = db.get(WaitingEntry, n.id)
        if w:
            w.status = "LEFT"
        n.status = "CLOSED"
    return {"waiting": _waiting(db, n.id), "need": need_summary(n)}


@router.post("/documents", status_code=201)
async def upload(file: UploadFile = File(...), doc_type: str = Form(...), need_id: str | None = Form(None),
                 actor: Actor = Depends(customer_actor), db: Session = DB):
    data = await file.read(docs.MAX_BYTES + 1)
    d = docs.ingest(db, actor.id, doc_type=doc_type, filename=file.filename or "upload", declared_mime=file.content_type
                    or "", data=data, need_id=uuid.UUID(need_id) if need_id else None)
    # Resume a journey waiting for documents (REQUEST_MISSING_ITEM)
    if d.pipeline_state == "STORED":
        for n in db.execute(select(FinancialNeed).where(FinancialNeed.customer_id == actor.id,
                                                        FinancialNeed.journey_id.is_not(None))).scalars():
            gi = db.get(GraphInstance, n.journey_id)
            if gi and gi.current_node == "REQUEST_MISSING_ITEM" and gi.status == "WAITING":
                from weza.domains.need.service import system_resume
                system_resume(db, gi.id, "document_uploaded")
    return docs.describe(d)


@router.get("/documents")
def list_documents(actor: Actor = Depends(customer_actor), db: Session = DB):
    rows = db.execute(select(Document).where(Document.customer_id == actor.id).order_by(Document.created_at.desc())).scalars()
    return {"documents": [docs.describe(d) for d in rows], "types": docs.DOC_TYPES}


@router.get("/notifications")
def my_notifications(actor: Actor = Depends(customer_actor), db: Session = DB):
    rows = db.execute(select(Notification).where(Notification.recipient_type == "CUSTOMER",
                                                 Notification.recipient_id == actor.id)
                      .order_by(Notification.created_at.desc()).limit(50)).scalars()
    return {"notifications": [{"id": str(n.id), "title": n.title, "body": n.body, "link": n.link,
                               "at": n.created_at.isoformat(), "read": n.read_at is not None} for n in rows]}


@router.post("/notifications/read")
def mark_read(actor: Actor = Depends(customer_actor), db: Session = DB):
    for n in db.execute(select(Notification).where(Notification.recipient_id == actor.id,
                                                   Notification.read_at.is_(None))).scalars():
        n.read_at = utcnow()
    return {"ok": True}
