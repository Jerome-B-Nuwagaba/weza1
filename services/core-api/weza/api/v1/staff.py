"""WEZA Staff — institution onboarding (Goal 2).

The staff surface for bringing an institution into the marketplace: list, create in Draft, record the primary
contact, create the administrator, review readiness, activate or pause. Every route requires a WEZA staff
session and a permission, so an institution user, a customer or an anonymous caller gets nothing.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from weza.api.deps import DB, require_step_up, weza_actor
from weza.domains.institution import staff as staff_svc
from weza.domains.trust import policy
from weza.platform.context import Actor
from weza.platform.controls import rate_limit

router = APIRouter(prefix="/staff", tags=["staff"])
W = Depends(weza_actor)


# ------------------------------------------------------------------ list and create


@router.get("/institutions")
def institutions(status: str | None = None, q: str | None = Query(None, max_length=120),
                 actor: Actor = W, db: Session = DB):
    """Every institution, its status and whether it is ready to trade."""
    rows = staff_svc.list_institutions(db, actor, status=status, q=q)
    return {"institutions": rows,
            "counts": {s: sum(1 for i in rows if i["status"] == s)
                       for s in sorted({i["status"] for i in rows})}}


class InstitutionIn(BaseModel):
    legal_name: str = Field(..., min_length=2, max_length=200)
    display_name: str = Field("", max_length=120)
    institution_type: str = Field("Other", max_length=40)
    country_code: str = Field("UG", max_length=2)
    licence_no: str = Field("", max_length=80)
    regulator: str = Field("", max_length=80)
    description: str = Field("", max_length=2000)
    website: str = Field("", max_length=200)


@router.post("/institutions", status_code=201)
def create_institution(body: InstitutionIn, actor: Actor = W, db: Session = DB):
    """Create an institution in Draft. It receives nothing until it is activated."""
    rate_limit(db, f"staff:create_institution:{actor.id}", 100, 3600)
    inst = staff_svc.create_draft(db, actor, body.model_dump())
    return staff_svc.detail(db, actor, inst)


# ------------------------------------------------------------------ detail


@router.get("/institutions/{inst_id}")
def institution(inst_id: uuid.UUID, actor: Actor = W, db: Session = DB):
    return staff_svc.detail(db, actor, staff_svc.get(db, inst_id))


# ------------------------------------------------------------------ primary contact


class ContactIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    email: str = Field(..., max_length=200)
    phone: str = Field("", max_length=40)
    title: str = Field("", max_length=120)
    kind: str = Field("REPRESENTATIVE", max_length=20)


@router.put("/institutions/{inst_id}/contact")
def set_contact(inst_id: uuid.UUID, body: ContactIn, actor: Actor = W, db: Session = DB):
    """Record the contact WEZA reaches first."""
    inst = staff_svc.get(db, inst_id)
    staff_svc.set_primary_contact(db, actor, inst, body.model_dump())
    return staff_svc.detail(db, actor, inst)


# ------------------------------------------------------------------ administrator


class AdministratorIn(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=160)
    email: str = Field(..., max_length=200)
    password: str = Field(..., min_length=12, max_length=200)


@router.post("/institutions/{inst_id}/administrator", status_code=201)
def create_administrator(inst_id: uuid.UUID, body: AdministratorIn, actor: Actor = W, db: Session = DB):
    """Create the institution's administrator. Share the initial password with them securely."""
    rate_limit(db, f"staff:create_administrator:{actor.id}", 100, 3600)
    inst = staff_svc.get(db, inst_id)
    created = staff_svc.create_administrator(db, actor, inst, body.model_dump())
    return {**staff_svc.detail(db, actor, inst), "administrator": created}


# ------------------------------------------------------------------ readiness


@router.get("/institutions/{inst_id}/readiness")
def readiness(inst_id: uuid.UUID, actor: Actor = W, db: Session = DB):
    """The activation checklist: four conditions, all of which must hold before activation."""
    inst = staff_svc.get(db, inst_id)
    policy.require(actor, "admin.institution_onboard")
    return staff_svc.readiness(db, inst)


# ------------------------------------------------------------------ activation and pause


class ActionIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1000)


@router.post("/institutions/{inst_id}/activate")
def activate(inst_id: uuid.UUID, body: ActionIn, actor: Actor = W, db: Session = DB):
    """Activate the institution. Refused unless every readiness condition holds."""
    require_step_up(actor)
    inst = staff_svc.get(db, inst_id)
    staff_svc.activate(db, actor, inst, body.reason)
    return staff_svc.detail(db, actor, inst)


@router.post("/institutions/{inst_id}/pause")
def pause(inst_id: uuid.UUID, body: ActionIn, actor: Actor = W, db: Session = DB):
    """Pause the institution. It stops receiving opportunities immediately."""
    require_step_up(actor)
    inst = staff_svc.get(db, inst_id)
    staff_svc.pause(db, actor, inst, body.reason)
    return staff_svc.detail(db, actor, inst)
