"""WEZA Staff institution onboarding (Goal 2).

WEZA staff bring an institution into the marketplace: they create it, record the primary contact WEZA reaches
first, give it an administrator, review whether it is ready to trade, and activate or pause it.

Everything here reuses the Goal 1 schema. The institution, its contacts, its users, its products, its mandate
and its routing rules are the same records the institution's own onboarding uses — a staff-created Draft
institution and an institution that applied to join differ only in who filled the form and how far along the
lifecycle they are. There is no parallel "staff institution" table to drift out of step.

The four readiness conditions are the ones Goal 2 names: an administrator, an active product, an active
appetite/mandate and a routing configuration. Activation is refused until all four hold.
"""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.appetite.models import Appetite, AppetiteVersion
from weza.domains.commercial.models import Contract
from weza.domains.identity import service as identity
from weza.domains.identity.models import Membership, User
from weza.domains.institution import service as inst_svc
from weza.domains.institution.models import Contact, Institution, RoutingRule, ServiceTarget
from weza.domains.product.models import Product
from weza.domains.trust import policy
from weza.domains.trust import roles as canon
from weza.domains.trust.service import audit
from weza.platform.context import Actor
from weza.platform.db import utcnow
from weza.platform.errors import Forbidden, NotFound, ValidationFailed
from weza.platform.events import emit

#: The lifecycle states a staff-created institution passes through before it can trade.
DRAFT = "DRAFT"

#: Every spelling of the administrator role — the canonical name and the working one.
ADMIN_ROLES = set(canon.spellings(canon.INSTITUTION_ADMIN))


def _require_staff(actor: Actor, permission: str) -> None:
    """WEZA staff only. A tenant actor never reaches this code path, but the check is explicit."""
    if not actor.is_weza:
        raise Forbidden("This area is for WEZA staff.", code="STAFF_ONLY")
    policy.require(actor, permission)


# ------------------------------------------------------------------ creation


def create_draft(db: Session, actor: Actor, data: dict) -> Institution:
    """Create an institution in Draft. It trades nothing until it is activated."""
    _require_staff(actor, "admin.institution_onboard")
    legal_name = (data.get("legal_name") or "").strip()
    if not legal_name:
        raise ValidationFailed("The institution's legal name is required.", code="LEGAL_NAME_REQUIRED")
    inst = Institution(
        legal_name=legal_name,
        display_name=(data.get("display_name") or legal_name).strip()[:120],
        institution_type=(data.get("institution_type") or "Other").strip()[:40],
        country_code=(data.get("country_code") or "UG").strip()[:2].upper(),
        licence_no=(data.get("licence_no") or "").strip()[:80],
        regulator=(data.get("regulator") or "").strip()[:80],
        status=DRAFT,
        profile={"description": (data.get("description") or "").strip(), "website": (data.get("website") or "").strip()},
        onboarding={"staff_created_by": actor.display, "staff_created_at": utcnow().isoformat(), "state": DRAFT},
    )
    db.add(inst)
    db.flush()
    audit(db, actor, "institution.draft_created", "institution", inst.id, institution_id=inst.id,
          after={"legal_name": inst.legal_name, "institution_type": inst.institution_type})
    emit(db, "InstitutionDraftCreated", topic="institution", aggregate_type="institution", aggregate_id=inst.id,
         institution_id=inst.id, data={"name": inst.display_name})
    return inst


def set_primary_contact(db: Session, actor: Actor, inst: Institution, data: dict) -> dict:
    """Record the contact WEZA reaches first. At most one primary contact per institution — the database
    enforces that, so any previous primary is cleared in the same transaction."""
    _require_staff(actor, "admin.institution_onboard")
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not name or not email:
        raise ValidationFailed("The primary contact needs a name and an email address.", code="CONTACT_REQUIRED")
    existing = db.execute(select(Contact).where(Contact.institution_id == inst.id,
                                                 Contact.is_primary.is_(True))).scalar_one_or_none()
    if existing is None:
        existing = db.execute(select(Contact).where(Contact.institution_id == inst.id,
                                                     Contact.kind == "REPRESENTATIVE")).scalars().first()
    before = inst_svc.contact_summary(existing) if existing else None
    # Clear the other primaries first: a unique partial index would refuse two.
    for other in db.execute(select(Contact).where(Contact.institution_id == inst.id,
                                                  Contact.is_primary.is_(True))).scalars():
        if other.id != existing.id:
            other.is_primary = False
    if existing is None:
        existing = Contact(institution_id=inst.id, kind="REPRESENTATIVE", name=name[:160], email=email[:200],
                           phone=(data.get("phone") or "").strip()[:40],
                           title=(data.get("title") or "").strip()[:120], is_primary=True)
        db.add(existing)
    else:
        existing.kind = (data.get("kind") or existing.kind or "REPRESENTATIVE").strip()[:20]
        existing.name = name[:160]
        existing.email = email[:200]
        existing.phone = (data.get("phone") or "").strip()[:40]
        existing.title = (data.get("title") or "").strip()[:120]
        existing.is_primary = True
    db.flush()
    audit(db, actor, "institution.primary_contact_set", "institution", inst.id, institution_id=inst.id,
          before=before, after=inst_svc.contact_summary(existing))
    return inst_svc.contact_summary(existing)


def create_administrator(db: Session, actor: Actor, inst: Institution, data: dict) -> dict:
    """Create the institution's administrator, using the same pattern the institution uses for its own staff:
    WEZA sets an initial password and shares it securely. The account is a normal INSTITUTION user, so the
    administrator signs in with the same login and MFA as any other institution user."""
    _require_staff(actor, "admin.institution_onboard")
    email = (data.get("email") or "").strip().lower()
    full_name = (data.get("full_name") or "").strip()
    password = data.get("password") or ""
    if not email or not full_name:
        raise ValidationFailed("The administrator needs a name and an email address.", code="ADMIN_REQUIRED")
    if len(password) < 12:
        raise ValidationFailed("Set an initial password of at least 12 characters and share it securely.",
                               code="WEAK_PASSWORD")
    user = identity.create_user(db, email=email, full_name=full_name, password=password, kind="INSTITUTION",
                                institution_id=inst.id, roles=[canon.INSTITUTION_ADMIN])
    audit(db, actor, "institution.administrator_created", "user", user.id, institution_id=inst.id,
          after={"email": user.email, "full_name": user.full_name, "roles": [canon.INSTITUTION_ADMIN]})
    emit(db, "InstitutionAdministratorCreated", topic="institution", aggregate_type="institution",
         aggregate_id=inst.id, institution_id=inst.id, data={"email": user.email})
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "status": user.status,
            "roles": [canon.INSTITUTION_ADMIN]}


# ------------------------------------------------------------------ readiness


def readiness(db: Session, inst: Institution) -> dict:
    """The activation checklist. Five conditions, all of which must hold before an institution may trade."""
    administrators = db.execute(
        select(func.count()).select_from(Membership).join(User, User.id == Membership.user_id)
        .where(Membership.institution_id == inst.id, User.status == "ACTIVE",
               canon.sql_any(Membership.roles, canon.INSTITUTION_ADMIN))
    ).scalar_one()
    officers = db.execute(
        select(func.count()).select_from(Membership).join(User, User.id == Membership.user_id)
        .where(Membership.institution_id == inst.id, User.status == "ACTIVE",
               canon.sql_any(Membership.roles, canon.INSTITUTION_OFFICER))
    ).scalar_one()
    products = db.execute(
        select(func.count()).select_from(Product)
        .where(Product.institution_id == inst.id, Product.status == "ACTIVE")
    ).scalar_one()
    # A mandate counts once it is approved, not only once it is live. A mandate can only go ACTIVE while its
    # institution is ACTIVE, and the institution can only go ACTIVE once it has a mandate — so demanding a
    # live mandate here would deadlock the flow. On activation WEZA promotes the approved mandate to ACTIVE
    # in the same transaction, so the guarantee that matters (an active institution carries active supply)
    # still holds. The institution's own activation checklist uses the same convention.
    approved_appetites = db.execute(
        select(func.count()).select_from(Appetite)
        .join(AppetiteVersion, AppetiteVersion.id == Appetite.active_version_id)
        .where(Appetite.institution_id == inst.id, Appetite.lifecycle_status == "APPROVED",
               AppetiteVersion.status == "APPROVED")
    ).scalar_one()
    live_appetites = db.execute(
        select(func.count()).select_from(Appetite)
        .join(AppetiteVersion, AppetiteVersion.id == Appetite.active_version_id)
        .where(Appetite.institution_id == inst.id, Appetite.lifecycle_status == "ACTIVE",
               AppetiteVersion.status == "APPROVED")
    ).scalar_one()
    # A rule that names nobody leaves every opportunity in the Unassigned queue, so routing only counts when an
    # active rule reaches someone who can work the opportunity: a named officer/manager, or a desk with an officer.
    from weza.domains.opportunity.service import _can_receive_work, _least_loaded_officer
    active_rules = db.execute(
        select(RoutingRule).where(RoutingRule.institution_id == inst.id, RoutingRule.active.is_(True))
    ).scalars().all()
    rules = len(active_rules)
    deliverable = sum(1 for rule in active_rules
                      if _can_receive_work(db, inst.id, rule.target_user_id)
                      or (rule.target_team_id and _least_loaded_officer(db, inst.id, rule.target_team_id)))
    appetite_detail = f"{live_appetites} active appetite(s)"
    if approved_appetites:
        appetite_detail += f" · {approved_appetites} approved, live on activation"
    conditions = [
        {"key": "administrator", "label": "Institution has an administrator", "done": administrators > 0,
         "detail": f"{administrators} active administrator(s)"},
        # Without an officer a live institution would be routed opportunities that nobody can work.
        {"key": "officer", "label": "Institution has an officer to work opportunities", "done": officers > 0,
         "detail": f"{officers} active officer(s)"},
        {"key": "product", "label": "At least one active product", "done": products > 0,
         "detail": f"{products} active product(s)"},
        {"key": "appetite", "label": "At least one active appetite / mandate",
         "done": (live_appetites + approved_appetites) > 0, "detail": appetite_detail},
        {"key": "routing", "label": "Routing sends opportunities to an officer", "done": deliverable > 0,
         "detail": f"{rules} active routing rule(s), {deliverable} reaching an active officer"},
    ]
    missing = [c for c in conditions if not c["done"]]
    return {"ready": not missing, "conditions": conditions, "missing": [c["key"] for c in missing],
            "next": missing[0] if missing else None}


# ------------------------------------------------------------------ activation and pause


def activate(db: Session, actor: Actor, inst: Institution, reason: str) -> dict:
    """Activate an institution — or bring a paused one back.

    The institution lifecycle stays authoritative: this walks the institution through the states it must pass
    (submitted, verified, configuring, ready) and only then makes it ACTIVE. Every step is audited, so the
    record shows exactly who did what and why.
    """
    _require_staff(actor, "admin.institution_activate")
    if inst.status in ("REJECTED", "CLOSED"):
        raise ValidationFailed("This institution can no longer be activated.", code="NOT_ACTIVATABLE")
    state = readiness(db, inst)
    if not state["ready"]:
        raise ValidationFailed(f"Not ready to activate: {state['next']['label']}.", code="ACTIVATION_NOT_READY",
                               details=[{"missing": key} for key in state["missing"]])
    if inst.status == DRAFT:
        inst_svc.set_status(db, actor, inst, "SUBMITTED", "Submitted by WEZA staff")
    if inst.status == "SUBMITTED":
        inst_svc.set_status(db, actor, inst, "UNDER_VERIFICATION", "Verification started by WEZA staff")
    if inst.status == "UNDER_VERIFICATION":
        inst_svc.set_status(db, actor, inst, "APPROVED", reason or "Approved by WEZA staff")
    if inst.status == "APPROVED":
        inst_svc.set_status(db, actor, inst, "CONFIGURING", "Workspace provisioned by WEZA staff")
    if inst.status == "CONFIGURING":
        inst_svc.set_status(db, actor, inst, "READY", "Readiness check passed")
    if inst.status == "READY":
        inst_svc.set_status(db, actor, inst, "ACTIVE", reason or "Activated on WEZA")
    elif inst.status == "PAUSED":
        inst_svc.set_status(db, actor, inst, "ACTIVE", reason or "Resumed on WEZA")
    elif inst.status == "SUSPENDED":
        inst_svc.set_status(db, actor, inst, "ACTIVE", reason or "Reinstated on WEZA")
    _provision_workspace(db, actor, inst)
    for ap in db.execute(select(Appetite).where(Appetite.institution_id == inst.id,
                                                Appetite.lifecycle_status == "APPROVED")).scalars():
        from weza.domains.appetite.service import activate_appetite
        activate_appetite(db, actor, ap, from_institution_activation=True)
    audit(db, actor, "institution.activated_by_staff", "institution", inst.id, institution_id=inst.id,
          after={"status": inst.status, "readiness": state["conditions"]}, reason=reason or None)
    return readiness(db, inst)


def pause(db: Session, actor: Actor, inst: Institution, reason: str) -> dict:
    """Pause an active institution. It stops receiving opportunities immediately: the market is re-cleared and
    the institution's live matches are invalidated."""
    _require_staff(actor, "admin.institution_activate")
    if inst.status != "ACTIVE":
        raise ValidationFailed("Only an active institution can be paused.", code="NOT_ACTIVE")
    state = readiness(db, inst)
    inst_svc.set_status(db, actor, inst, "PAUSED", reason)
    audit(db, actor, "institution.paused_by_staff", "institution", inst.id, institution_id=inst.id,
          before={"status": "ACTIVE"}, after={"status": "PAUSED", "readiness": state["conditions"]}, reason=reason)
    return readiness(db, inst)


def _provision_workspace(db: Session, actor: Actor, inst: Institution) -> None:
    """The workspace defaults a trading institution needs: a service target and a contract."""
    if db.get(ServiceTarget, inst.id) is None:
        db.add(ServiceTarget(institution_id=inst.id))
    if not db.execute(select(Contract).where(Contract.institution_id == inst.id)).first():
        db.add(Contract(institution_id=inst.id, plan="GROWTH", subscription_fee=1_500_000,
                        included_opportunities=20, opportunity_price=50_000, effective_from=date.today(),
                        qualified_definition={}))


# ------------------------------------------------------------------ reads


def list_institutions(db: Session, actor: Actor, *, status: str | None = None, q: str | None = None) -> list[dict]:
    """The staff list: every institution, its status and whether it is ready to trade."""
    _require_staff(actor, "admin.institution_onboard")
    query = select(Institution).order_by(Institution.created_at.desc())
    if status:
        query = query.where(Institution.status == status)
    if q:
        needle = f"%{q.strip().lower()}%"
        query = query.where(func.lower(Institution.display_name).like(needle)
                             | func.lower(Institution.legal_name).like(needle))
    out = []
    for inst in db.execute(query).scalars():
        state = readiness(db, inst)
        out.append({**inst_svc.summary(inst),
                    "created_at": inst.created_at.isoformat() if inst.created_at else None,
                    "primary_contact": inst_svc.primary_contact(db, inst),
                    "ready": state["ready"],
                    "missing": state["missing"]})
    return out


def detail(db: Session, actor: Actor, inst: Institution) -> dict:
    """Everything the staff detail page shows: identity, contact, people, supply, readiness."""
    _require_staff(actor, "admin.institution_onboard")
    members = db.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                         .where(Membership.institution_id == inst.id)).all()
    people = [{"id": str(u.id), "email": u.email, "full_name": u.full_name, "status": u.status,
               "roles": sorted(set(m.roles) & set(policy.INST_ROLES)),
               "is_administrator": bool(set(canon.expand(m.roles)) & ADMIN_ROLES)}
              for m, u in members]
    return {
        **inst_svc.summary(inst),
        "status_reason": inst.status_reason,
        "profile": inst.profile,
        "onboarding": inst.onboarding,
        "created_at": inst.created_at.isoformat() if inst.created_at else None,
        "primary_contact": inst_svc.primary_contact(db, inst),
        "contacts": [inst_svc.contact_summary(c) for c in db.execute(
            select(Contact).where(Contact.institution_id == inst.id)).scalars()],
        "people": people,
        "readiness": readiness(db, inst),
        "products": [{"id": str(p.id), "name": p.name, "status": p.status} for p in db.execute(
            select(Product).where(Product.institution_id == inst.id)).scalars()],
        "appetites": [{"id": str(a.id), "name": a.name, "status": a.lifecycle_status, "capacity": a.capacity_state}
                      for a in db.execute(select(Appetite).where(Appetite.institution_id == inst.id)).scalars()],
        "allowed_transitions": sorted(inst_svc.INSTITUTION_SM.transitions.get(inst.status, set())),
    }


def get(db: Session, inst_id: uuid.UUID) -> Institution:
    inst = db.get(Institution, inst_id)
    if inst is None:
        raise NotFound("Not found.")
    return inst
