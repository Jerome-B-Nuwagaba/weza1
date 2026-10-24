"""Institution workspace API (/inst). Tenant comes only from the authenticated token (TSD §47);
every route re-checks permissions server-side (TSD §29, §48)."""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from weza.api.deps import DB, institution_actor
from weza.domains.appetite import service as appetite_svc
from weza.domains.appetite.models import Appetite, AppetiteVersion
from weza.domains.commercial import service as commercial
from weza.domains.commercial.models import CommercialEvent, Dispute
from weza.domains.consent.models import Consent
from weza.domains.customer import documents as docs
from weza.domains.customer.models import Document
from weza.domains.identity import service as identity
from weza.domains.identity.models import Membership, User
from weza.domains.institution import service as inst_svc
from weza.domains.institution.models import (
    Contact,
    Institution,
    NotificationPref,
    RoutingRule,
    ServiceTarget,
    Team,
)
from weza.domains.intelligence import agents, assistant, insights
from weza.domains.matching import engine
from weza.domains.misc_models import Notification
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import (
    Assignment,
    InfoRequest,
    Insight,
    Opportunity,
    Outcome,
    Preview,
    ReasonSignal,
)
from weza.domains.product import service as product_svc
from weza.domains.product.models import Product, ProductVersion
from weza.domains.trust import policy
from weza.domains.trust.models import AuditEvent, PolicyDecisionLog
from weza.domains.trust.service import audit
from weza.domains.verification import service as verification
from weza.platform.context import Actor
from weza.platform.controls import flag, idempotent
from weza.platform.db import utcnow
from weza.platform.errors import NotFound, ValidationFailed

router = APIRouter(prefix="/inst", tags=["institution"])
A = Depends(institution_actor)


def _inst(db: Session, actor: Actor) -> Institution:
    return db.get(Institution, actor.institution_id)


# ------------------------------------------------------------------ workspace, onboarding, activation


@router.get("/workspace")
def workspace(actor: Actor = A, db: Session = DB):
    inst = _inst(db, actor)
    return {"institution": {**inst_svc.summary(inst), "profile": inst.profile,
                            "status_reason": inst.status_reason,
                            "primary_contact": inst_svc.primary_contact(db, inst)},
            "onboarding": inst_svc.checklist(db, inst),
            "permissions": policy.permissions_for(actor.roles),
            "teams": [{"id": str(t.id), "name": t.name} for t in db.execute(select(Team).where(
                Team.institution_id == inst.id)).scalars()],
            "features": {"preview": flag(db, "marketplace.preview", False)}}


@router.get("/contacts")
def contacts(actor: Actor = A, db: Session = DB):
    inst = _inst(db, actor)
    rows = db.execute(select(Contact).where(Contact.institution_id == inst.id).order_by(Contact.kind, Contact.name)).scalars()
    return {"contacts": [inst_svc.contact_summary(c) for c in rows],
            "primary_contact": inst_svc.primary_contact(db, inst)}


@router.put("/contacts/{contact_id}/primary")
def set_primary_contact(contact_id: uuid.UUID, actor: Actor = A, db: Session = DB):
    inst = _inst(db, actor)
    return inst_svc.set_primary_contact(db, actor, inst, contact_id)


@router.post("/activate")
def activate(actor: Actor = A, db: Session = DB):
    return inst_svc.activate(db, actor, _inst(db, actor))


class ProfileIn(BaseModel):
    display_name: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=1000)
    website: str | None = Field(None, max_length=200)
    regions_served: list[str] | None = None


@router.patch("/workspace")
def update_profile(body: ProfileIn, actor: Actor = A, db: Session = DB):
    policy.require(actor, "institution.settings")
    inst = _inst(db, actor)
    if body.display_name:
        inst.display_name = body.display_name
    inst.profile = {**inst.profile, **body.model_dump(exclude_none=True, exclude={"display_name"})}
    audit(db, actor, "institution.profile_updated", "institution", inst.id)
    return workspace(actor, db)


# ------------------------------------------------------------------ users & teams


@router.get("/users")
def users(actor: Actor = A, db: Session = DB):
    return {"users": opp_svc.team_members(db, actor.institution_id), "roles": policy.INST_ROLES,
            "role_labels": {r: policy.ROLE_LABELS[r] for r in policy.INST_ROLES},
            "teams": [{"id": str(t.id), "name": t.name} for t in db.execute(select(Team).where(
                Team.institution_id == actor.institution_id)).scalars()]}


class UserIn(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=160)
    email: str = Field(..., max_length=200)
    roles: list[str]
    team_id: str | None = None
    password: str = Field(..., min_length=12, max_length=200)


def _own_team(db: Session, actor: Actor, team_id: str | None) -> uuid.UUID | None:
    """A team id from the request must belong to the caller's institution (never trust ids across tenants)."""
    if not team_id:
        return None
    try:
        tid = uuid.UUID(team_id)
    except ValueError:
        raise ValidationFailed("Unknown team.", code="UNKNOWN_TEAM") from None
    t = db.execute(select(Team).where(Team.id == tid,
                                     Team.institution_id == actor.institution_id)).scalar_one_or_none()
    if t is None:
        raise NotFound("Not found.")
    return tid


@router.post("/users", status_code=201)
def add_user(body: UserIn, actor: Actor = A, db: Session = DB):
    policy.require(actor, "users.manage")
    roles = [r for r in body.roles if r in policy.INST_ROLES]
    if not roles:
        raise ValidationFailed("Choose at least one role.")
    u = identity.create_user(db, email=body.email, full_name=body.full_name, password=body.password,
                             kind="INSTITUTION", institution_id=actor.institution_id, roles=roles,
                             team_id=_own_team(db, actor, body.team_id))
    audit(db, actor, "users.created", "user", u.id, after={"roles": roles})
    return users(actor, db)


class UserPatch(BaseModel):
    roles: list[str] | None = None
    team_id: str | None = None
    status: str | None = Field(None, pattern="^(ACTIVE|DISABLED)$")


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, actor: Actor = A, db: Session = DB):
    policy.require(actor, "users.manage")
    m = db.execute(select(Membership).where(Membership.user_id == user_id,
                                                  Membership.institution_id == actor.institution_id)).scalar_one_or_none()
    if m is None or m.institution_id != actor.institution_id:
        raise NotFound("Not found.")
    before = {"roles": list(m.roles), "team": str(m.team_id) if m.team_id else None}
    if body.roles is not None:
        roles = [r for r in body.roles if r in policy.INST_ROLES]
        if not roles:
            raise ValidationFailed("Choose at least one role.", code="ROLES_REQUIRED")
        if user_id == actor.id and "INST_ADMIN" not in roles:
            raise ValidationFailed("You can't remove your own administrator role.")
        m.roles = roles
    if body.team_id is not None:
        m.team_id = _own_team(db, actor, body.team_id)
    if body.status:
        if user_id == actor.id:
            raise ValidationFailed("You can't disable yourself.")
        db.get(User, user_id).status = body.status
    audit(db, actor, "users.updated", "user", user_id, before=before, after=body.model_dump(exclude_none=True))
    return users(actor, db)


class PasswordResetIn(BaseModel):
    new_password: str = Field(..., min_length=12, max_length=200)


@router.post("/users/{user_id}/password")
def reset_user_password(user_id: uuid.UUID, body: PasswordResetIn, actor: Actor = A, db: Session = DB):
    """Institution administrator sets a new password for a colleague (e.g. forgotten password). Their sessions end;
    share the new password with them securely."""
    policy.require(actor, "users.manage")
    m = db.execute(select(Membership).where(Membership.user_id == user_id,
                                                  Membership.institution_id == actor.institution_id)).scalar_one_or_none()
    if m is None or m.institution_id != actor.institution_id:
        raise NotFound("Not found.")
    if user_id == actor.id:
        raise ValidationFailed("Use 'Change my password' for your own account.", code="USE_SELF_SERVICE")
    identity.set_password(db, db.get(User, user_id), body.new_password)
    audit(db, actor, "users.password_reset", "user", user_id)
    return {"ok": True}


class PasswordChangeIn(BaseModel):
    current_password: str = Field(..., max_length=200)
    new_password: str = Field(..., min_length=12, max_length=200)


@router.post("/password")
def change_my_password(body: PasswordChangeIn, actor: Actor = A, db: Session = DB):
    """Any institution user changes their own password. All their other sessions are signed out."""
    from weza.platform import crypto
    from weza.platform.controls import rate_limit
    rate_limit(db, f"pwchange:{actor.id}", 5, 900, "Too many attempts. Try again in 15 minutes.")
    user = db.get(User, actor.id)
    if not crypto.verify_password(body.current_password, user.password_hash):
        # 422, not 401: a wrong current password must not look like an expired session to the client
        raise ValidationFailed("Your current password is incorrect.", code="INVALID_CURRENT_PASSWORD")
    identity.set_password(db, user, body.new_password)
    audit(db, actor, "users.password_changed", "user", user.id)
    return {"ok": True, "note": "Password changed. Other signed-in sessions have been ended."}


class TeamIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)


@router.post("/teams", status_code=201)
def add_team(body: TeamIn, actor: Actor = A, db: Session = DB):
    policy.require(actor, "team.manage")
    t = Team(institution_id=actor.institution_id, name=body.name)
    db.add(t)
    db.flush()
    audit(db, actor, "team.created", "team", t.id)
    return {"id": str(t.id), "name": t.name}


@router.patch("/teams/{team_id}")
def rename_team(team_id: uuid.UUID, body: TeamIn, actor: Actor = A, db: Session = DB):
    policy.require(actor, "team.manage")
    t = db.get(Team, _own_team(db, actor, str(team_id)))
    before = t.name
    t.name = body.name.strip()
    audit(db, actor, "team.renamed", "team", t.id, before={"name": before}, after={"name": t.name})
    return {"id": str(t.id), "name": t.name}


@router.delete("/teams/{team_id}")
def remove_team(team_id: uuid.UUID, actor: Actor = A, db: Session = DB):
    """Removing a team never strands work: members and routing rules must be moved first."""
    policy.require(actor, "team.manage")
    tid = _own_team(db, actor, str(team_id))
    members = db.execute(select(func.count()).select_from(Membership).where(Membership.team_id == tid)).scalar_one()
    rules = db.execute(select(func.count()).select_from(RoutingRule).where(RoutingRule.target_team_id == tid)
                       ).scalar_one()
    open_work = db.execute(select(func.count()).select_from(Assignment).join(
        Opportunity, Opportunity.id == Assignment.opportunity_id).where(
        Assignment.team_id == tid, Opportunity.state.in_(list(opp_svc.OPEN_STATES)))).scalar_one()
    if members or rules or open_work:
        raise ValidationFailed(f"Move this team's {members} member(s), {rules} routing rule(s) and {open_work} open "
                               "opportunity(ies) first.", code="TEAM_IN_USE")
    db.delete(db.get(Team, tid))
    audit(db, actor, "team.removed", "team", tid)
    return users(actor, db)


# ------------------------------------------------------------------ products


def _pv_dict(pv: ProductVersion) -> dict:
    return {"id": str(pv.id), "version": pv.version, "status": pv.status, "name": pv.name, "family": pv.family,
            "terms": pv.terms, "rules": pv.rules, "requirements": pv.requirements, "provenance": pv.provenance,
            "ruleset_hash": pv.ruleset_hash, "author_id": str(pv.author_id) if pv.author_id else None,
            "approver_id": str(pv.approver_id) if pv.approver_id else None,
            "approved_at": pv.approved_at.isoformat() if pv.approved_at else None, "review_note": pv.review_note,
            "created_at": pv.created_at.isoformat()}


@router.get("/products")
def products(actor: Actor = A, db: Session = DB):
    policy.require(actor, "product.read")
    out = []
    for p in db.execute(select(Product).where(Product.institution_id == actor.institution_id)
                        .order_by(Product.created_at)).scalars():
        latest = db.execute(select(ProductVersion).where(ProductVersion.product_id == p.id)
                            .order_by(ProductVersion.version.desc()).limit(1)).scalar_one()
        active = db.get(ProductVersion, p.active_version_id) if p.active_version_id else None
        out.append({"id": str(p.id), "name": p.name, "family": p.family, "status": p.status,
                    "active_version": active.version if active else None, "latest_version": latest.version,
                    "latest_status": latest.status, "terms": (active or latest).terms,
                    "rules": len((active or latest).rules), "pending_approval": latest.status == "PENDING_APPROVAL"})
    return {"products": out, "families": product_svc.FAMILIES, "rule_fields": sorted(product_svc.RULE_FIELDS),
            "doc_types": docs.DOC_TYPES}


@router.get("/products/{product_id}")
def product_detail(product_id: uuid.UUID, actor: Actor = A, db: Session = DB):
    policy.require(actor, "product.read")
    p = product_svc.get_owned(db, actor, product_id)
    versions = db.execute(select(ProductVersion).where(ProductVersion.product_id == p.id)
                          .order_by(ProductVersion.version.desc())).scalars().all()
    names = {u.id: u.full_name for u in db.execute(select(User).where(User.id.in_(
        [v.author_id for v in versions if v.author_id] + [v.approver_id for v in versions if v.approver_id]))).scalars()}
    return {"id": str(p.id), "name": p.name, "family": p.family, "status": p.status,
            "active_version_id": str(p.active_version_id) if p.active_version_id else None,
            "versions": [{**_pv_dict(v), "author": names.get(v.author_id), "approver": names.get(v.approver_id)}
                         for v in versions], "can_approve": policy.has(actor, "product.approve"),
            "me": str(actor.id)}


class ProductIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    family: str
    terms: dict
    rules: list[dict] = []
    requirements: list[dict] = []
    provenance: dict | None = None


@router.post("/products", status_code=201)
def create_product(body: ProductIn, actor: Actor = A, db: Session = DB):
    pv = product_svc.create(db, actor, body.model_dump(), provenance=body.provenance)
    return {"product_id": str(pv.product_id), "version": _pv_dict(pv)}


@router.put("/products/{product_id}")
def edit_product(product_id: uuid.UUID, body: ProductIn, actor: Actor = A, db: Session = DB):
    p = product_svc.get_owned(db, actor, product_id)
    return _pv_dict(product_svc.new_version(db, actor, p, body.model_dump()))


class ReviewIn(BaseModel):
    approve: bool
    note: str | None = Field(None, max_length=1000)


def _pending_or_draft(db: Session, product_id) -> ProductVersion:
    pv = db.execute(select(ProductVersion).where(ProductVersion.product_id == product_id,
                                                 ProductVersion.status.in_(["DRAFT", "PENDING_APPROVAL"]))
                    .order_by(ProductVersion.version.desc()).limit(1)).scalar_one_or_none()
    if pv is None:
        raise ValidationFailed("There is no draft or pending version.")
    return pv


@router.post("/products/{product_id}/submit")
def submit_product(product_id: uuid.UUID, actor: Actor = A, db: Session = DB):
    product_svc.get_owned(db, actor, product_id)
    product_svc.submit(db, actor, _pending_or_draft(db, product_id))
    return product_detail(product_id, actor, db)


@router.post("/products/{product_id}/review")
def review_product(product_id: uuid.UUID, body: ReviewIn, actor: Actor = A, db: Session = DB):
    product_svc.get_owned(db, actor, product_id)
    product_svc.review(db, actor, _pending_or_draft(db, product_id), body.approve, body.note)
    return product_detail(product_id, actor, db)


class StatusIn(BaseModel):
    status: str
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/products/{product_id}/status")
def product_status(product_id: uuid.UUID, body: StatusIn, actor: Actor = A, db: Session = DB):
    p = product_svc.get_owned(db, actor, product_id)
    product_svc.set_status(db, actor, p, body.status, body.reason)
    return product_detail(product_id, actor, db)


@router.post("/products/extract")
async def extract_product(file: UploadFile = File(...), actor: Actor = A, db: Session = DB):
    """AI-assisted extraction from an approved product document (FSD §18). Returns a proposal only."""
    policy.require(actor, "product.create")
    data = await file.read(docs.MAX_BYTES + 1)
    if len(data) > docs.MAX_BYTES:
        raise ValidationFailed("File is larger than 10 MB.")
    ok, result = docs.get_scanner().scan(data)
    if not ok:
        raise ValidationFailed("We couldn't check this file right now. Please try again shortly."
                               if result == docs.SCAN_UNAVAILABLE else "This file failed our security check.")
    text = ""
    if data.startswith(b"%PDF"):
        import io

        from pypdf import PdfReader
        try:
            text = "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages[:30])
        except Exception as exc:  # noqa: BLE001
            raise ValidationFailed("We couldn't read this PDF.") from exc
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationFailed("Upload a PDF or a plain-text document.") from exc
    if len(text.strip()) < 40:
        raise ValidationFailed("The document has too little readable text.")
    proposal = agents.product_rules(db, text, subject=f"extract:{actor.institution_id}")
    audit(db, actor, "product.ai_extraction", "institution", actor.institution_id,
          after={"source": proposal.get("source"), "rules": len(proposal.get("rules") or [])})
    return {"proposal": proposal, "filename": file.filename,
            "notice": "AI proposals are drafts. Nothing is active until reviewed and approved by an authorised user."}


# ------------------------------------------------------------------ appetite


def _av_dict(av: AppetiteVersion) -> dict:
    return {"id": str(av.id), "version": av.version, "status": av.status, "name": av.name,
            "product_ids": [str(x) for x in av.product_ids or []], "criteria": av.criteria,
            "min_match_score": av.min_match_score, "target_count": av.target_count,
            "target_value": float(av.target_value) if av.target_value else None, "capacity_limits": av.capacity_limits,
            "campaign_from": av.campaign_from.isoformat() if av.campaign_from else None,
            "campaign_to": av.campaign_to.isoformat() if av.campaign_to else None,
            "simulation_run_id": str(av.simulation_run_id) if av.simulation_run_id else None,
            "author_id": str(av.author_id) if av.author_id else None, "review_note": av.review_note,
            "approved_at": av.approved_at.isoformat() if av.approved_at else None,
            "mandate": av.mandate}


@router.get("/appetites")
def appetites(actor: Actor = A, db: Session = DB):
    policy.require(actor, "appetite.read")
    out = []
    for ap in db.execute(select(Appetite).where(Appetite.institution_id == actor.institution_id)
                         .order_by(Appetite.created_at)).scalars():
        latest = db.execute(select(AppetiteVersion).where(AppetiteVersion.appetite_id == ap.id)
                            .order_by(AppetiteVersion.version.desc()).limit(1)).scalar_one()
        cur = db.get(AppetiteVersion, ap.active_version_id) if ap.active_version_id else None
        version = cur or latest
        crit = version.criteria or []

        def pick(field, criteria=crit):
            for c in criteria:
                if c.get("field") == field:
                    return c.get("value")
            return None

        products = []
        if version.product_ids:
            products = [{"id": str(x.id), "name": x.name} for x in db.execute(
                select(Product).where(Product.id.in_(list(version.product_ids)))).scalars()]
        out.append({"id": str(ap.id), "name": ap.name, "lifecycle_status": ap.lifecycle_status,
                    "capacity_state": ap.capacity_state, "capacity_override": ap.capacity_override,
                    "fulfilled_count": ap.fulfilled_count, "fulfilled_value": float(ap.fulfilled_value or 0),
                    "active_version": cur.version if cur else None, "latest_version": latest.version,
                    "latest_status": latest.status, "target_count": (cur or latest).target_count,
                    "target_value": float((cur or latest).target_value) if (cur or latest).target_value else None,
                    "min_match_score": (cur or latest).min_match_score, "criteria": len((cur or latest).criteria),
                    "products": products, "customer_type": pick("customer_type"), "sector": pick("sector"),
                    "region": pick("region"), "amount_range": pick("amount"),
                    "business_age_months": pick("business_age_months"),
                    "routing_team_id": (version.capacity_limits or {}).get("routing_team_id"),
                    "mandate": (cur or latest).mandate})
    return {"appetites": out}


@router.get("/appetites/{appetite_id}")
def appetite_detail(appetite_id: uuid.UUID, actor: Actor = A, db: Session = DB):
    policy.require(actor, "appetite.read")
    ap = appetite_svc.get_owned(db, actor, appetite_id)
    versions = db.execute(select(AppetiteVersion).where(AppetiteVersion.appetite_id == ap.id)
                          .order_by(AppetiteVersion.version.desc())).scalars().all()
    from weza.domains.matching.models import SimulationRun
    sims = {s.id: s.result for s in db.execute(select(SimulationRun).where(
        SimulationRun.id.in_([v.simulation_run_id for v in versions if v.simulation_run_id]))).scalars()}
    return {"id": str(ap.id), "name": ap.name, "lifecycle_status": ap.lifecycle_status,
            "capacity_state": ap.capacity_state, "capacity_override": ap.capacity_override,
            "fulfilled_count": ap.fulfilled_count, "fulfilled_value": float(ap.fulfilled_value or 0),
            "active_version_id": str(ap.active_version_id) if ap.active_version_id else None,
            "versions": [{**_av_dict(v), "simulation": sims.get(v.simulation_run_id)} for v in versions],
            "can_approve": policy.has(actor, "appetite.activate"), "can_edit": policy.has(actor, "appetite.edit"),
            "me": str(actor.id)}


class AppetiteIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    product_ids: list[str]
    criteria: list[dict] = []
    min_match_score: int = 60
    target_count: int | None = None
    target_value: float | None = None
    capacity_limits: dict = {}
    campaign_from: str | None = None
    campaign_to: str | None = None
    # The mandate dimensions (Goal 1 §4). Each is optional; an empty list or null means the
    # institution is not restricted on that dimension.
    customer_types: list[str] = []
    sectors: list[str] = []
    regions: list[str] = []
    min_amount: float | None = None
    max_amount: float | None = None
    min_business_age_months: int | None = None


@router.post("/appetites", status_code=201)
def create_appetite(body: AppetiteIn, actor: Actor = A, db: Session = DB):
    av = appetite_svc.create(db, actor, body.model_dump())
    return {"appetite_id": str(av.appetite_id), "version": _av_dict(av)}


@router.put("/appetites/{appetite_id}")
def edit_appetite(appetite_id: uuid.UUID, body: AppetiteIn, actor: Actor = A, db: Session = DB):
    ap = appetite_svc.get_owned(db, actor, appetite_id)
    return _av_dict(appetite_svc.new_version(db, actor, ap, body.model_dump()))


def _draftish(db: Session, appetite_id) -> AppetiteVersion:
    av = db.execute(select(AppetiteVersion).where(AppetiteVersion.appetite_id == appetite_id,
                                                  AppetiteVersion.status.in_(["DRAFT", "SIMULATED"]))
                    .order_by(AppetiteVersion.version.desc()).limit(1)).scalar_one_or_none()
    if av is None:
        raise ValidationFailed("There is no draft version to act on.")
    return av


@router.post("/appetites/{appetite_id}/simulate")
def simulate_appetite(appetite_id: uuid.UUID, actor: Actor = A, db: Session = DB):
    appetite_svc.get_owned(db, actor, appetite_id)
    return appetite_svc.simulate_version(db, actor, _draftish(db, appetite_id))


@router.post("/appetites/{appetite_id}/review")
def review_appetite(appetite_id: uuid.UUID, body: ReviewIn, actor: Actor = A, db: Session = DB):
    appetite_svc.get_owned(db, actor, appetite_id)
    appetite_svc.approve(db, actor, _draftish(db, appetite_id), body.approve, body.note)
    return appetite_detail(appetite_id, actor, db)


@router.post("/appetites/{appetite_id}/status")
def appetite_status(appetite_id: uuid.UUID, body: StatusIn, actor: Actor = A, db: Session = DB):
    ap = appetite_svc.get_owned(db, actor, appetite_id)
    if body.status == "ACTIVE" and ap.lifecycle_status == "APPROVED":
        appetite_svc.activate_appetite(db, actor, ap)
    else:
        appetite_svc.set_lifecycle(db, actor, ap, body.status, body.reason)
    return appetite_detail(appetite_id, actor, db)


class CapacityIn(BaseModel):
    override: str | None = None
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/appetites/{appetite_id}/capacity")
def appetite_capacity(appetite_id: uuid.UUID, body: CapacityIn, actor: Actor = A, db: Session = DB):
    ap = appetite_svc.get_owned(db, actor, appetite_id)
    appetite_svc.set_capacity_override(db, actor, ap, body.override, body.reason)
    return appetite_detail(appetite_id, actor, db)


class WhatIfIn(BaseModel):
    product_ids: list[str]
    criteria: list[dict] = []
    min_match_score: int = 60


@router.post("/simulate")
def what_if(body: WhatIfIn, actor: Actor = A, db: Session = DB):
    return appetite_svc.simulate_adhoc(db, actor, body.model_dump())


# ------------------------------------------------------------------ sandbox (synthetic customers, TSD §74)


@router.post("/sandbox/runs")
def sandbox(actor: Actor = A, db: Session = DB):
    policy.require(actor, "sandbox.run")
    from weza.domains.intelligence.sandbox import run_sandbox
    return run_sandbox(db, actor)


# ------------------------------------------------------------------ routing & notifications


@router.get("/routing")
def routing(actor: Actor = A, db: Session = DB):
    st = db.get(ServiceTarget, actor.institution_id) or ServiceTarget(ack_within_minutes=120,
                                                                      first_contact_within_minutes=1440,
                                                                      escalate_after_minutes=2880)
    return {"rules": [{"id": str(r.id), "name": r.name, "priority": r.priority, "conditions": r.conditions,
                       "target_team_id": str(r.target_team_id) if r.target_team_id else None,
                       "target_user_id": str(r.target_user_id) if r.target_user_id else None, "active": r.active}
                      for r in db.execute(select(RoutingRule).where(RoutingRule.institution_id == actor.institution_id)
                                          .order_by(RoutingRule.priority)).scalars()],
            "targets": {"ack_within_minutes": st.ack_within_minutes,
                        "first_contact_within_minutes": st.first_contact_within_minutes,
                        "escalate_after_minutes": st.escalate_after_minutes},
            "teams": [{"id": str(t.id), "name": t.name} for t in db.execute(select(Team).where(
                Team.institution_id == actor.institution_id)).scalars()],
            "products": [{"id": str(p.id), "name": p.name} for p in db.execute(select(Product).where(
                Product.institution_id == actor.institution_id)).scalars()],
            "can_edit": policy.has(actor, "routing.manage")}


class RoutingIn(BaseModel):
    rules: list[dict]
    targets: dict | None = None


@router.put("/routing")
def save_routing(body: RoutingIn, actor: Actor = A, db: Session = DB):
    inst_svc.save_routing(db, actor, actor.institution_id, body.rules, body.targets)
    return routing(actor, db)


@router.get("/notification-prefs")
def get_prefs(actor: Actor = A, db: Session = DB):
    rows = db.execute(select(NotificationPref).where(NotificationPref.institution_id == actor.institution_id,
                                                     NotificationPref.user_id.is_(None))).scalars().all()
    prefs = [{"event_type": p.event_type, "channels": p.channels, "min_priority": p.min_priority, "digest": p.digest}
             for p in rows] or inst_svc.default_notification_prefs()
    return {"prefs": prefs, "configured": bool(rows), "events": inst_svc.DEFAULT_NOTIFICATION_EVENTS}


class PrefsIn(BaseModel):
    prefs: list[dict]


@router.put("/notification-prefs")
def put_prefs(body: PrefsIn, actor: Actor = A, db: Session = DB):
    policy.require(actor, "institution.settings")
    inst_svc.save_notification_prefs(db, actor, actor.institution_id, body.prefs)
    return get_prefs(actor, db)


# ------------------------------------------------------------------ command centre, my day, feed


@router.get("/command-centre")
def command_centre(actor: Actor = A, db: Session = DB):
    return insights.command_centre(db, actor)


def _feed_query(db: Session, actor: Actor, view: str | None, state: str | None, freshness: str | None,
                min_match: int | None, sector: str | None, q: str | None):
    query = select(Opportunity).where(Opportunity.institution_id == actor.institution_id)
    query = query.outerjoin(Assignment, Assignment.opportunity_id == Opportunity.id)
    if policy.officer_only(actor) or view == "mine":
        query = query.where(Assignment.user_id == actor.id)
    if view == "unassigned":
        query = query.where(or_(Assignment.user_id.is_(None), Assignment.opportunity_id.is_(None)),
                            Opportunity.state.in_(list(opp_svc.OPEN_STATES)))
    elif view == "open" or view is None:
        query = query.where(Opportunity.state.in_(list(opp_svc.OPEN_STATES)))
    elif view == "closed":
        query = query.where(~Opportunity.state.in_(list(opp_svc.OPEN_STATES)))
    if state:
        query = query.where(Opportunity.state == state)
    if freshness:
        query = query.where(Opportunity.freshness == freshness)
    if min_match:
        query = query.where(Opportunity.match_score >= min_match)
    if sector:
        query = query.where(Opportunity.sector == sector)
    if q:
        query = query.where(Opportunity.reference.ilike(f"%{q.strip()[:20]}%"))
    return query


@router.get("/opportunities")
def feed(view: str | None = None, state: str | None = None, freshness: str | None = None, min_match: int | None = None,
         sector: str | None = None, q: str | None = None, sort: str = "priority", limit: int = Query(100, ge=1, le=200),
         actor: Actor = A, db: Session = DB):
    """Intelligent Opportunity Feed (FSD §23). Ranking factors are explicit (FSD-FED-001)."""
    policy.require(actor, "opportunity.read_meta")
    rows = db.execute(_feed_query(db, actor, view, state, freshness, min_match, sector, q).limit(500)).scalars().all()
    users = {u.id: u.full_name for u in db.execute(select(User).join(Membership, Membership.user_id == User.id).where(
        Membership.institution_id == actor.institution_id)).scalars()}
    pending = opp_svc.open_info_request_counts(db, [o.id for o in rows])
    ids = verification.latest_statuses(db, [o.customer_id for o in rows])
    items = [opp_svc.summary(db, o, users=users, open_requests=pending, identity_statuses=ids) for o in rows]
    prio = {"URGENT": 0, "HIGH": 1, "NORMAL": 2}
    if sort == "priority":
        items.sort(key=lambda s: (prio.get(s["priority"], 3), s["minutes_to_target"] if s["minutes_to_target"] is not None
                                  else 10**9, -s["match_score"], -s["amount"]))
    elif sort == "match":
        items.sort(key=lambda s: -s["match_score"])
    elif sort == "amount":
        items.sort(key=lambda s: -s["amount"])
    elif sort == "age":
        items.sort(key=lambda s: -s["age_hours"])
    return {"items": items[:limit], "total": len(items),
            "ranking": {"priority": "Priority (match ≥90 and/or ≥ UGX 50M), then nearest service target, then match "
                                    "score, then amount", "match": "Match score", "amount": "Requested amount",
                        "age": "Waiting longest"}[sort] if sort in ("priority", "match", "amount", "age") else sort,
            "members": [{"id": str(k), "name": v} for k, v in users.items()]}


@router.get("/my-day")
def my_day(actor: Actor = A, db: Session = DB):
    policy.require(actor, "opportunity.read_meta")
    rows = db.execute(select(Opportunity).join(Assignment, Assignment.opportunity_id == Opportunity.id).where(
        Assignment.user_id == actor.id, Opportunity.state.in_(list(opp_svc.OPEN_STATES)))).scalars().all()
    pending = opp_svc.open_info_request_counts(db, [o.id for o in rows])
    ids = verification.latest_statuses(db, [o.customer_id for o in rows])
    items = [opp_svc.summary(db, o, open_requests=pending, identity_statuses=ids) for o in rows]
    sections = {
        "new": [i for i in items if i["state"] in ("ROUTED", "RECEIVED", "ASSIGNED")],
        "follow_up": [i for i in items if i["state"] in ("CONTACTED", "INFORMATION_REQUESTED", "PROCEEDING")],
        "awaiting_outcome": [i for i in items if i["state"] in ("SUBMITTED_TO_INSTITUTION", "REPORTED_APPROVED")],
    }
    for k in sections:
        sections[k].sort(key=lambda s: (s["minutes_to_target"] if s["minutes_to_target"] is not None else 10**9,
                                        -s["match_score"]))
    return {"sections": sections, "counts": {k: len(v) for k, v in sections.items()},
            "ordering": "Nearest service target first, then highest match."}


@router.get("/opportunities/{opp_id}")
def opportunity(opp_id: uuid.UUID, actor: Actor = A, db: Session = DB):
    out = opp_svc.view(db, actor, opp_id)
    out["can_update"] = policy.has(actor, "opportunity.update_status")
    out["can_assign"] = policy.has(actor, "opportunity.assign")
    out["doc_types"] = docs.DOC_TYPES
    from weza.domains.customer.service import EDITABLE, FIELD_LABELS
    consented = set(out["consent"]["categories"] or [])
    out["fact_fields"] = {k: FIELD_LABELS[k] for k in sorted(EDITABLE) if policy.fact_category(k) in consented}
    out["members"] = [m for m in opp_svc.team_members(db, actor.institution_id)
                      if {"OFFICER", "MANAGER"} & set(m["role_set"])]
    return out


class AssignIn(BaseModel):
    user_id: uuid.UUID
    reason: str | None = Field(None, max_length=500)


@router.post("/opportunities/{opp_id}/assign")
def assign(opp_id: uuid.UUID, body: AssignIn, actor: Actor = A, db: Session = DB):
    o = db.execute(select(Opportunity).where(Opportunity.id == opp_id,
                                             Opportunity.institution_id == actor.institution_id)).scalar_one_or_none()
    if o is None:
        raise NotFound("Not found.")
    policy.require_tenant(actor, o.institution_id)  # before any permission check: never reveal another tenant's ids
    opp_svc.assign_manual(db, actor, o, body.user_id, body.reason)
    return opportunity(opp_id, actor, db)


class StatusUpdateIn(BaseModel):
    state: str
    note: str | None = Field(None, max_length=1000)


@router.post("/opportunities/{opp_id}/status")
def update_status(opp_id: uuid.UUID, body: StatusUpdateIn, idempotency_key: str | None = Header(None),
                  actor: Actor = A, db: Session = DB):
    o = db.execute(select(Opportunity).where(Opportunity.id == opp_id,
                                             Opportunity.institution_id == actor.institution_id)).scalar_one_or_none()
    if o is None:
        raise NotFound("Not found.")
    policy.require_tenant(actor, o.institution_id)

    def run():
        opp_svc.update_status(db, actor, o, body.state, body.note)
        return {"state": o.state}
    idempotent(db, idempotency_key, f"status:{opp_id}", body.model_dump(), run)
    return opportunity(opp_id, actor, db)


class NoteIn(BaseModel):
    note: str = Field(..., min_length=1, max_length=1000)


@router.post("/opportunities/{opp_id}/note")
def add_note(opp_id: uuid.UUID, body: NoteIn, actor: Actor = A, db: Session = DB):
    """An internal note on a routed opportunity — the institution's own record. It is never shown to the customer."""
    o = db.execute(select(Opportunity).where(Opportunity.id == opp_id,
                                             Opportunity.institution_id == actor.institution_id)).scalar_one_or_none()
    if o is None:
        raise NotFound("Not found.")
    policy.require_tenant(actor, o.institution_id)
    opp_svc.add_internal_note(db, actor, o, body.note)
    return opportunity(opp_id, actor, db)


class OutcomeIn(BaseModel):
    state: str
    reason_category: str | None = None
    reason_note: str | None = Field(None, max_length=1000)
    approved_amount: float | None = Field(None, ge=0)
    disbursed_amount: float | None = Field(None, ge=0)
    disbursed_on: date | None = None
    # Indicative terms (approvals only)
    tenor_months: int | None = Field(None, ge=1, le=360)
    interest_rate: float | None = Field(None, ge=0, le=100)
    rate_period: str | None = Field(None, pattern="^(MONTHLY|ANNUAL)$")
    fees: float | None = Field(None, ge=0)
    monthly_repayment: float | None = Field(None, ge=0)
    conditions: str | None = Field(None, max_length=1000)
    terms_valid_until: date | None = None


@router.post("/opportunities/{opp_id}/outcome")
def outcome(opp_id: uuid.UUID, body: OutcomeIn, idempotency_key: str | None = Header(None), actor: Actor = A,
            db: Session = DB):
    o = db.execute(select(Opportunity).where(Opportunity.id == opp_id,
                                             Opportunity.institution_id == actor.institution_id)).scalar_one_or_none()
    if o is None:
        raise NotFound("Not found.")
    policy.require_tenant(actor, o.institution_id)

    def run():
        out = opp_svc.report_outcome(db, actor, o, **body.model_dump())
        return {"outcome_id": str(out.id)}
    idempotent(db, idempotency_key, f"outcome:{opp_id}", body.model_dump(mode="json"), run)
    return opportunity(opp_id, actor, db)


class InfoRequestIn(BaseModel):
    kind: str = Field(..., pattern="^(DOCUMENT|QUESTION)$")
    message: str = Field(..., min_length=1, max_length=1000)
    doc_type: str | None = None
    due_in_days: int | None = Field(None, ge=1, le=30)
    fact_key: str | None = Field(None, max_length=60)


@router.post("/opportunities/{opp_id}/info-requests", status_code=201)
def create_info_request(opp_id: uuid.UUID, body: InfoRequestIn, idempotency_key: str | None = Header(None),
                        actor: Actor = A, db: Session = DB):
    o = db.execute(select(Opportunity).where(Opportunity.id == opp_id,
                                             Opportunity.institution_id == actor.institution_id)).scalar_one_or_none()
    if o is None:
        raise NotFound("Not found.")
    policy.require_tenant(actor, o.institution_id)

    def run():
        r = opp_svc.request_info(db, actor, o, **body.model_dump())
        return {"request_id": str(r.id)}
    idempotent(db, idempotency_key, f"info_request:{opp_id}", body.model_dump(), run)
    return opportunity(opp_id, actor, db)


class CancelInfoIn(BaseModel):
    reason: str | None = Field(None, max_length=500)


@router.post("/opportunities/{opp_id}/info-requests/{request_id}/cancel")
def cancel_info_request(opp_id: uuid.UUID, request_id: uuid.UUID, body: CancelInfoIn, actor: Actor = A,
                        db: Session = DB):
    o = db.execute(select(Opportunity).where(Opportunity.id == opp_id,
                                             Opportunity.institution_id == actor.institution_id)).scalar_one_or_none()
    r = db.execute(select(InfoRequest).where(InfoRequest.id == request_id,
                                             InfoRequest.opportunity_id == opp_id,
                                             InfoRequest.institution_id == actor.institution_id)).scalar_one_or_none()
    if o is None or r is None:
        raise NotFound("Not found.")
    opp_svc.cancel_info_request(db, actor, o, r, body.reason)
    return opportunity(opp_id, actor, db)


@router.delete("/opportunities/{opp_id}/info-requests/{request_id}")
def delete_info_request(opp_id: uuid.UUID, request_id: uuid.UUID, reason: str | None = Query(None, max_length=500),
                        actor: Actor = A, db: Session = DB):
    """Spec alias for cancel. The request is closed as CANCELLED and kept for audit — never deleted."""
    return cancel_info_request(opp_id, request_id, CancelInfoIn(reason=reason), actor, db)


@router.get("/opportunities/{opp_id}/documents/{doc_id}")
def opportunity_document(opp_id: uuid.UUID, doc_id: uuid.UUID, actor: Actor = A, db: Session = DB):
    """Documents stream only through the Disclosure Gateway; never public URLs (TSD §51)."""
    o = db.execute(select(Opportunity).where(Opportunity.id == opp_id,
                                             Opportunity.institution_id == actor.institution_id)).scalar_one_or_none()
    if o is None:
        raise NotFound("Not found.")
    policy.require_tenant(actor, o.institution_id)
    decision = policy.decide_opportunity_access(db, actor, o, db.get(Assignment, o.id), db.get(Consent, o.consent_id))
    d = db.execute(select(Document).where(Document.id == doc_id,
                                          Document.customer_id == o.customer_id,
                                          Document.pipeline_state.in_(("STORED", "CONFIRMED")))).scalar_one_or_none()
    if decision.result != "PERMIT" or "documents" not in decision.fields or d is None or d.customer_id != o.customer_id:
        raise NotFound("Not found.")
    data = docs.read_bytes(db, d.id)
    if data is None:
        raise NotFound("Not found.")
    audit(db, actor, "document.downloaded", "document", d.id, institution_id=o.institution_id)
    return Response(content=data, media_type=d.mime,
                    headers={"Content-Disposition": f'inline; filename="{d.doc_type}{_ext(d.mime)}"'})


def _ext(mime: str) -> str:
    return {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}.get(mime, "")


# ------------------------------------------------------------------ previews & interest (flagged)


@router.get("/previews")
def previews(actor: Actor = A, db: Session = DB):
    policy.require(actor, "preview.read")
    if not flag(db, "marketplace.preview", False):
        return {"enabled": False, "previews": []}
    rows = db.execute(select(Preview).where(Preview.institution_id == actor.institution_id,
                                            Preview.expires_at > utcnow()).order_by(Preview.created_at.desc())).scalars()
    return {"enabled": True, "reasons": opp_svc.REASON_SIGNALS,
            "previews": [{"id": str(p.id), **p.payload, "interest": p.interest_state,
                          "expires_at": p.expires_at.isoformat()} for p in rows]}


class InterestIn(BaseModel):
    state: str = Field(..., pattern="^(INTERESTED|NEED_MORE_INFORMATION|NOT_INTERESTED)$")
    reason: str | None = None  # required with NOT_INTERESTED — one of opp_svc.REASON_SIGNALS
    note: str | None = Field(None, max_length=500)


@router.post("/previews/{preview_id}/interest")
def interest(preview_id: uuid.UUID, body: InterestIn, actor: Actor = A, db: Session = DB):
    policy.require(actor, "preview.interest")
    p = db.execute(select(Preview).where(Preview.id == preview_id,
                                         Preview.institution_id == actor.institution_id)).scalar_one_or_none()
    if p is None or p.institution_id != actor.institution_id:
        raise NotFound("Not found.")
    if body.state == "NOT_INTERESTED" and body.reason not in opp_svc.REASON_SIGNALS:
        raise ValidationFailed("Tell us why you're passing — it feeds your near-match intelligence.",
                               code="REASON_REQUIRED")
    p.interest_state, p.interest_by = body.state, actor.id
    signal = db.execute(select(ReasonSignal).where(ReasonSignal.preview_id == p.id)).scalar_one_or_none()
    if body.state == "NOT_INTERESTED":
        if signal is None:
            signal = ReasonSignal(institution_id=p.institution_id, preview_id=p.id, need_id=p.need_id,
                                  reason=body.reason, created_by=actor.id)
            db.add(signal)
        signal.reason, signal.note = body.reason, body.note
    elif signal is not None:
        db.delete(signal)  # the institution changed its mind; the pass reason no longer applies
    audit(db, actor, "preview.interest", "preview", p.id,
          after={"state": body.state, "reason": body.reason if body.state == "NOT_INTERESTED" else None})
    if body.state in ("INTERESTED", "NEED_MORE_INFORMATION"):
        from weza.domains.need.models import FinancialNeed
        from weza.domains.notification.service import notify_customer
        need = db.get(FinancialNeed, p.need_id)
        if need and need.customer_id and body.state == "INTERESTED":
            notify_customer(db, need.customer_id, "InstitutionInterest", title="An institution is interested",
                            body="A participating institution is interested in your request. Open WEZA to review your "
                                 "options — nothing is shared unless you choose to.", link="/start")
        elif need and need.customer_id:
            # Pre-consent: the institution is not named and receives nothing; the customer may strengthen the request.
            notify_customer(db, need.customer_id, "InstitutionNeedsMore", title="Your request could go further",
                            body="A participating institution would like more detail before it can consider your "
                                 "request. Adding documents or completing your profile in WEZA may open more options.",
                            link="/c/documents")
    return {"ok": True, "note": "Interest is not approval and does not disclose the customer's identity."}


# ------------------------------------------------------------------ team, intelligence, reports


@router.get("/team")
def team(actor: Actor = A, db: Session = DB):
    policy.require(actor, "team.manage")
    members = opp_svc.team_members(db, actor.institution_id)
    rows = db.execute(select(Opportunity, Assignment).outerjoin(Assignment, Assignment.opportunity_id == Opportunity.id)
                      .where(Opportunity.institution_id == actor.institution_id)).all()
    stats: dict = {m["id"]: {"open": 0, "contacted": 0, "breached": 0, "assigned_30d": 0, "aging": {"<1d": 0, "1-3d": 0,
                                                                                                     "3-7d": 0, ">7d": 0}}
                   for m in members}
    unassigned_high = []
    now = utcnow()
    cutoff = now - timedelta(days=30)
    for o, a in rows:
        if a is None or a.user_id is None:
            if o.state in opp_svc.OPEN_STATES and o.match_score >= 85:
                unassigned_high.append(opp_svc.summary(db, o, a))
            continue
        s = stats.get(str(a.user_id))
        if s is None:
            continue
        if o.state in opp_svc.OPEN_STATES:
            s["open"] += 1
            age = (now - o.qualified_at).days
            s["aging"]["<1d" if age < 1 else "1-3d" if age < 3 else "3-7d" if age < 7 else ">7d"] += 1
        if a.first_contact_at and cutoff <= a.first_contact_at <= now:
            s["contacted"] += 1
        if a.breach_count:
            s["breached"] += 1
        if a.assigned_at and cutoff <= a.assigned_at <= now:
            s["assigned_30d"] += 1
    return {"members": [{**m, **stats[m["id"]], "contact_rate": round(100 * stats[m["id"]]["contacted"] /
                                                                      stats[m["id"]]["assigned_30d"])
                         if stats[m["id"]]["assigned_30d"] else None} for m in members],
            "unassigned_high_match": unassigned_high}


@router.get("/intelligence/radius")
def radius(actor: Actor = A, db: Session = DB):
    policy.require(actor, "analytics.read")
    return engine.radius(db, actor.institution_id)


@router.get("/intelligence/demand")
def demand(days: int = Query(90, ge=1, le=365), actor: Actor = A, db: Session = DB):
    policy.require(actor, "analytics.read")
    return insights.demand_intelligence(db, actor.institution_id, days)


@router.get("/intelligence/reason-signals")
def reason_signals(days: int = Query(90, ge=1, le=365), actor: Actor = A, db: Session = DB):
    policy.require(actor, "analytics.read")
    return insights.reason_signals(db, actor.institution_id, days)


@router.get("/intelligence/product-gaps")
def product_gaps(actor: Actor = A, db: Session = DB):
    policy.require(actor, "analytics.read")
    return {"gaps": insights.product_gaps(db),
            "note": "Decision support only. WEZA never creates or activates products for you."}


@router.get("/intelligence/insights")
def list_insights(actor: Actor = A, db: Session = DB):
    policy.require(actor, "analytics.read")
    rows = db.execute(select(Insight).where(Insight.institution_id == actor.institution_id)
                      .order_by(Insight.created_at.desc())).scalars()
    return {"insights": [{"id": str(i.id), "kind": i.kind, "title": i.title, "narrative": i.narrative,
                          "evidence": i.evidence, "status": i.status, "appetite_id": str(i.appetite_id) if i.appetite_id
                          else None, "decision_note": i.decision_note, "created_at": i.created_at.isoformat()}
                         for i in rows]}


class InsightDecision(BaseModel):
    status: str = Field(..., pattern="^(DISMISSED|ACTIONED)$")
    note: str = Field(..., min_length=3, max_length=1000)


@router.post("/intelligence/insights/{insight_id}")
def decide_insight(insight_id: uuid.UUID, body: InsightDecision, actor: Actor = A, db: Session = DB):
    policy.require(actor, "appetite.edit")
    i = db.execute(select(Insight).where(Insight.id == insight_id,
                                         Insight.institution_id == actor.institution_id)).scalar_one_or_none()
    if i is None or i.institution_id != actor.institution_id:
        raise NotFound("Not found.")
    i.status, i.decision_note, i.decided_by = body.status, body.note, actor.id
    audit(db, actor, "insight.decided", "insight", i.id, after={"status": body.status}, reason=body.note)
    return list_insights(actor, db)


class AskIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


@router.post("/ask")
def ask(body: AskIn, actor: Actor = A, db: Session = DB):
    return assistant.ask(db, actor, body.question)


@router.get("/reports/outcomes")
def report_outcomes(actor: Actor = A, db: Session = DB):
    policy.require(actor, "analytics.read")
    opps = db.execute(select(Opportunity).where(Opportunity.institution_id == actor.institution_id)).scalars().all()
    outs = db.execute(select(Outcome).where(Outcome.institution_id == actor.institution_id)).scalars().all()
    from collections import Counter
    stage_order = ["ROUTED", "RECEIVED", "ASSIGNED", "CONTACTED", "INFORMATION_REQUESTED", "PROCEEDING",
                   "SUBMITTED_TO_INSTITUTION", "REPORTED_APPROVED", "REPORTED_DISBURSED"]
    reached = Counter()
    from weza.domains.opportunity.models import Activity
    acts = db.execute(select(Activity.opportunity_id, Activity.kind).where(
        Activity.opportunity_id.in_([o.id for o in opps]))).all() if opps else []
    seen = {(oid, k) for oid, k in acts}
    for o in opps:
        for st in stage_order:
            if (o.id, st) in seen or (st in ("RECEIVED",) and o.received_at):
                reached[st] += 1
    decline = Counter(opp_svc.DECLINE_REASONS.get(x.reason_category or "", "Other") for x in outs
                      if x.state == "REPORTED_DECLINED")
    by_product = Counter((o.snapshot.get("product_version") or {}).get("name") for o in opps)
    return {"funnel": [{"stage": s, "count": reached.get(s, 0)} for s in stage_order], "total": len(opps),
            "decline_reasons": dict(decline), "by_product": dict(by_product),
            "reported_approved_value": float(sum(x.approved_amount or 0 for x in outs if x.state == "REPORTED_APPROVED")),
            "reported_disbursed_value": float(sum(x.disbursed_amount or 0 for x in outs if x.state == "REPORTED_DISBURSED")),
            "label": "Approvals and disbursements are as reported by your institution."}


@router.get("/reports/export")
def export(actor: Actor = A, db: Session = DB):
    """CSV export of non-identifiable opportunity data (audited)."""
    policy.require(actor, "analytics.read")
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["reference", "state", "amount", "purpose", "customer_type", "sector", "district", "match_score",
                "quality_score", "qualified_at", "product"])
    for o in db.execute(select(Opportunity).where(Opportunity.institution_id == actor.institution_id)).scalars():
        w.writerow([o.reference, o.state, float(o.amount), o.purpose_category, o.customer_type, o.sector, o.district,
                    round(o.match_score), o.quality_score, o.qualified_at.isoformat(),
                    (o.snapshot.get("product_version") or {}).get("name")])
    audit(db, actor, "reports.exported", "institution", actor.institution_id)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="weza-opportunities.csv"'})


# ------------------------------------------------------------------ billing & disputes


@router.get("/billing")
def billing(period: str | None = None, actor: Actor = A, db: Session = DB):
    policy.require(actor, "billing.view")
    c = commercial.active_contract(db, actor.institution_id)
    events = db.execute(select(CommercialEvent).where(CommercialEvent.institution_id == actor.institution_id)
                        .order_by(CommercialEvent.created_at.desc()).limit(200)).scalars().all()
    refs = {o.id: o.reference for o in db.execute(select(Opportunity).where(
        Opportunity.id.in_([e.opportunity_id for e in events if e.opportunity_id]))).scalars()} if events else {}
    disputes = {d.commercial_event_id: d for d in db.execute(select(Dispute).where(
        Dispute.institution_id == actor.institution_id)).scalars()}
    return {"contract": {"plan": c.plan, "subscription_fee": float(c.subscription_fee),
                         "included_opportunities": c.included_opportunities,
                         "opportunity_price": float(c.opportunity_price), "currency": c.currency,
                         "duplicate_window_days": c.duplicate_window_days, "dispute_window_days": c.dispute_window_days,
                         "qualified_definition": {**commercial.DEFAULT_DEFINITION, **(c.qualified_definition or {})}}
            if c else None,
            "statement": commercial.statement(db, actor.institution_id, period),
            "events": [{"id": str(e.id), "kind": e.kind, "status": e.status, "amount": float(e.amount),
                        "reference": refs.get(e.opportunity_id), "period": e.billing_period,
                        "created_at": e.created_at.isoformat(), "evaluation": e.evaluation,
                        "dispute": {"id": str(disputes[e.id].id), "state": disputes[e.id].state,
                                    "decision": disputes[e.id].decision} if e.id in disputes else None}
                       for e in events],
            "dispute_reasons": commercial.DISPUTE_REASONS, "can_dispute": policy.has(actor, "billing.dispute")}


class DisputeIn(BaseModel):
    reason: str
    description: str = Field(..., min_length=10, max_length=4000)


@router.post("/billing/events/{event_id}/dispute", status_code=201)
def dispute(event_id: uuid.UUID, body: DisputeIn, idempotency_key: str | None = Header(None), actor: Actor = A,
            db: Session = DB):
    policy.require(actor, "billing.dispute")

    def run():
        d = commercial.open_dispute(db, actor, event_id, body.reason, body.description)
        return {"dispute_id": str(d.id)}
    return idempotent(db, idempotency_key, f"dispute:{event_id}", body.model_dump(), run)


# ------------------------------------------------------------------ compliance, notifications


@router.get("/audit")
def audit_log(actor: Actor = A, db: Session = DB, limit: int = Query(200, ge=1, le=500)):
    policy.require(actor, "consent.audit")
    events = db.execute(select(AuditEvent).where(AuditEvent.institution_id == actor.institution_id)
                        .order_by(AuditEvent.at.desc()).limit(limit)).scalars()
    access = db.execute(select(PolicyDecisionLog).where(PolicyDecisionLog.institution_id == actor.institution_id)
                        .order_by(PolicyDecisionLog.at.desc()).limit(limit)).scalars()
    consents = db.execute(select(Consent).where(Consent.institution_id == actor.institution_id)
                          .order_by(Consent.granted_at.desc()).limit(limit)).scalars()
    return {"audit": [{"at": e.at.isoformat(), "actor": e.actor_display, "action": e.action, "object": e.object_type,
                       "object_id": e.object_id, "reason": e.reason} for e in events],
            "access": [{"at": a.at.isoformat(), "actor": a.actor, "resource": a.resource, "result": a.result,
                        "fields": a.fields_permitted} for a in access],
            "consents": [{"id": str(c.id), "status": c.status, "version": c.template_version,
                          "categories": c.data_categories, "granted_at": c.granted_at.isoformat(),
                          "withdrawn_at": c.withdrawn_at.isoformat() if c.withdrawn_at else None,
                          "opportunity_id": str(c.opportunity_id) if c.opportunity_id else None} for c in consents]}


@router.get("/notifications")
def notifications(actor: Actor = A, db: Session = DB):
    rows = db.execute(select(Notification).where(Notification.recipient_id == actor.id, Notification.channel == "in_app")
                      .order_by(Notification.created_at.desc()).limit(50)).scalars()
    return {"notifications": [{"id": str(n.id), "title": n.title, "body": n.body, "link": n.link, "priority": n.priority,
                               "at": n.created_at.isoformat(), "read": n.read_at is not None,
                               "ack_required": n.ack_required, "acked": n.acked_at is not None} for n in rows],
            "unread": db.execute(select(func.count()).select_from(Notification).where(
                Notification.recipient_id == actor.id, Notification.channel == "in_app",
                Notification.read_at.is_(None))).scalar_one()}


@router.post("/notifications/{notification_id}/ack")
def ack(notification_id: uuid.UUID, actor: Actor = A, db: Session = DB):
    n = db.execute(select(Notification).where(Notification.id == notification_id,
                                              Notification.recipient_id == actor.id,
                                              Notification.institution_id == actor.institution_id)).scalar_one_or_none()
    if n is None or n.recipient_id != actor.id:
        raise NotFound("Not found.")
    n.read_at = n.read_at or utcnow()
    if n.ack_required:
        n.acked_at = utcnow()
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(actor: Actor = A, db: Session = DB):
    for n in db.execute(select(Notification).where(Notification.recipient_id == actor.id,
                                                   Notification.read_at.is_(None))).scalars():
        n.read_at = utcnow()
    return {"ok": True}


_ = Form
