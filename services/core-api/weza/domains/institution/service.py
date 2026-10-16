"""Institution registration, WEZA verification, workspace, users, routing, onboarding graph & activation
(FSD §16–21; blueprint G2). Zero integration: everything an institution provides is configured here."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.appetite.models import Appetite
from weza.domains.commercial.models import Contract
from weza.domains.identity import service as identity
from weza.domains.identity.models import Membership, User
from weza.domains.institution.models import (
    Contact,
    Institution,
    NotificationPref,
    RoutingRule,
    ServiceTarget,
    Team,
)
from weza.domains.misc_models import ReviewItem
from weza.domains.product.models import Product
from weza.domains.trust import policy
from weza.domains.trust.service import audit
from weza.platform.context import Actor
from weza.platform.controls import StateMachine
from weza.platform.db import utcnow
from weza.platform.errors import ValidationFailed
from weza.platform.events import emit

TERMS_VERSION = "2026.1"
INSTITUTION_SM = StateMachine("Institution", {
    "DRAFT": {"SUBMITTED"}, "SUBMITTED": {"UNDER_VERIFICATION", "REJECTED"},
    "UNDER_VERIFICATION": {"APPROVED", "REJECTED"}, "APPROVED": {"CONFIGURING", "SUSPENDED"},
    "CONFIGURING": {"READY", "SUSPENDED"}, "READY": {"ACTIVE", "CONFIGURING", "SUSPENDED"},
    "ACTIVE": {"PAUSED", "SUSPENDED", "CLOSED"}, "PAUSED": {"ACTIVE", "SUSPENDED", "CLOSED"},
    "SUSPENDED": {"ACTIVE", "CONFIGURING", "CLOSED"}, "REJECTED": set(), "CLOSED": set(),
})
DEFAULT_NOTIFICATION_EVENTS = ["OpportunityRouted", "HighMatchOpportunity", "OpportunityAssigned",
                               "ServiceTargetApproaching", "ServiceTargetBreached", "InfoRequestFulfilled",
                               "InfoRequestExpired", "DailyBrief", "AppetiteInsight"]
PRIORITIES = ("NORMAL", "HIGH", "URGENT")


def apply(db: Session, data: dict) -> tuple[Institution, User]:
    """Join WEZA: creates the institution (SUBMITTED) and its first administrator (FSD §16)."""
    if not data.get("accept_terms"):
        raise ValidationFailed("Marketplace terms must be accepted.", code="TERMS_REQUIRED")
    inst = Institution(legal_name=data["legal_name"].strip(), display_name=(data.get("display_name") or
                       data["legal_name"]).strip()[:120], institution_type=data["institution_type"],
                       licence_no=data.get("licence_no", ""), regulator=data.get("regulator", ""),
                       status="SUBMITTED", terms_version=TERMS_VERSION, terms_accepted_at=utcnow(),
                       profile={"description": data.get("description", ""), "website": data.get("website", "")})
    db.add(inst)
    db.flush()
    for kind in ("REPRESENTATIVE", "BUSINESS", "COMPLIANCE"):
        c = data.get(kind.lower())
        if c:
            db.add(Contact(institution_id=inst.id, kind=kind, name=c["name"], email=c["email"],
                           phone=c.get("phone", ""), title=c.get("title", "")))
    admin = identity.create_user(db, email=data["admin_email"], full_name=data["admin_name"],
                                 password=data["admin_password"], kind="INSTITUTION", institution_id=inst.id,
                                 roles=["INST_ADMIN"])
    actor = Actor(kind="INSTITUTION_USER", id=admin.id, institution_id=inst.id, display=admin.full_name)
    audit(db, actor, "institution.applied", "institution", inst.id, institution_id=inst.id,
          after={"legal_name": inst.legal_name, "terms_version": TERMS_VERSION})
    emit(db, "InstitutionApplicationSubmitted", topic="institution", aggregate_type="institution",
         aggregate_id=inst.id, institution_id=inst.id, data={"name": inst.display_name})
    db.add(ReviewItem(kind="INSTITUTION_VERIFICATION", title=f"Verify {inst.legal_name}", object_type="institution",
                      object_id=str(inst.id), severity="MEDIUM", dedupe_key=f"verify:{inst.id}", detail={}))
    return inst, admin


def set_status(db: Session, actor: Actor, inst: Institution, to: str, reason: str | None = None) -> None:
    INSTITUTION_SM.check(inst.status, to)
    before = inst.status
    inst.status = to
    inst.status_reason = reason
    if to == "APPROVED":
        inst.verified_by, inst.verified_at = actor.display, utcnow()
    if to == "ACTIVE" and inst.activated_at is None:
        inst.activated_at = utcnow()
    audit(db, actor, f"institution.{to.lower()}", "institution", inst.id, institution_id=inst.id,
          before={"status": before}, after={"status": to}, reason=reason)
    event = {"APPROVED": "InstitutionVerified", "REJECTED": "InstitutionRejected", "ACTIVE": "InstitutionActivated",
             "PAUSED": "InstitutionPaused", "SUSPENDED": "InstitutionSuspended", "CLOSED": "InstitutionClosed"}.get(to)
    if event:
        emit(db, event, topic="institution", aggregate_type="institution", aggregate_id=inst.id,
             institution_id=inst.id, data={"from": before, "reason": reason})


def verify(db: Session, actor: Actor, inst: Institution, approve: bool, reason: str) -> None:
    """HUMAN_VERIFY_INSTITUTION (AL0). Provisions the workspace defaults on approval."""
    policy.require(actor, "admin.verify_institution")
    if not reason:
        raise ValidationFailed("A reason is required.")
    if inst.status == "SUBMITTED":
        set_status(db, actor, inst, "UNDER_VERIFICATION", "Review started")
    if not approve:
        set_status(db, actor, inst, "REJECTED", reason)
        return
    set_status(db, actor, inst, "APPROVED", reason)
    set_status(db, actor, inst, "CONFIGURING", "Workspace provisioned")
    if db.get(ServiceTarget, inst.id) is None:
        db.add(ServiceTarget(institution_id=inst.id))
    for item in db.execute(select(ReviewItem).where(ReviewItem.dedupe_key == f"verify:{inst.id}")).scalars():
        item.status, item.resolved_by, item.resolution = "RESOLVED", actor.display, reason


def checklist(db: Session, inst: Institution) -> dict:
    """READINESS_CHECK node of the onboarding graph (FSD §21). Each item links to the node that fixes it."""
    members = db.execute(select(Membership).where(Membership.institution_id == inst.id)).scalars().all()
    roles = {r for m in members for r in m.roles}
    items = [
        {"key": "verified", "label": "Institution verified by WEZA", "done": inst.status not in
         ("DRAFT", "SUBMITTED", "UNDER_VERIFICATION", "REJECTED"), "link": "/institution/settings"},
        {"key": "users", "label": "Users and roles configured (an officer and a manager or admin)",
         "done": "OFFICER" in roles and bool(roles & {"MANAGER", "INST_ADMIN"}), "link": "/institution/users"},
        {"key": "product", "label": "At least one approved product", "done": db.execute(select(func.count()).select_from(
            Product).where(Product.institution_id == inst.id, Product.status.in_(["ACTIVE", "PAUSED"]))).scalar_one() > 0,
         "link": "/institution/products"},
        {"key": "appetite", "label": "At least one approved appetite / mandate", "done": db.execute(
            select(func.count()).select_from(Appetite).where(Appetite.institution_id == inst.id,
                                                             Appetite.lifecycle_status.in_(["APPROVED", "ACTIVE",
                                                                                            "PAUSED"]))).scalar_one() > 0,
         "link": "/institution/appetite"},
        {"key": "routing", "label": "Opportunity routing configured", "done": db.execute(select(func.count()).select_from(
            RoutingRule).where(RoutingRule.institution_id == inst.id, RoutingRule.active.is_(True))).scalar_one() > 0,
         "link": "/institution/routing"},
        {"key": "notifications", "label": "Notification preferences configured", "done": db.execute(
            select(func.count()).select_from(NotificationPref).where(NotificationPref.institution_id == inst.id)
        ).scalar_one() > 0, "link": "/institution/notifications"},
        {"key": "terms", "label": "Marketplace data-sharing terms accepted", "done": inst.terms_accepted_at is not None,
         "link": "/institution/settings"},
    ]
    ready = all(i["done"] for i in items)
    return {"status": inst.status, "items": items, "ready": ready,
            "next": next((i for i in items if not i["done"]), None)}


def activate(db: Session, actor: Actor, inst: Institution) -> dict:
    policy.require(actor, "institution.activate")
    c = checklist(db, inst)
    if not c["ready"]:
        raise ValidationFailed(f"Not ready to activate: {c['next']['label']}.", code="ACTIVATION_NOT_READY",
                               details=[{"missing": i["key"]} for i in c["items"] if not i["done"]])
    if inst.status == "CONFIGURING":
        set_status(db, actor, inst, "READY", "Readiness check passed")
    set_status(db, actor, inst, "ACTIVE", "ACTIVATE ON WEZA")
    for ap in db.execute(select(Appetite).where(Appetite.institution_id == inst.id,
                                                Appetite.lifecycle_status == "APPROVED")).scalars():
        from weza.domains.appetite.service import activate_appetite
        activate_appetite(db, actor, ap, from_institution_activation=True)
    if not db.execute(select(Contract).where(Contract.institution_id == inst.id)).first():
        from datetime import date
        db.add(Contract(institution_id=inst.id, plan="GROWTH", subscription_fee=1_500_000, included_opportunities=20,
                        opportunity_price=50_000, effective_from=date.today(), qualified_definition={}))
    return checklist(db, inst)


def save_routing(db: Session, actor: Actor, institution_id: uuid.UUID, rules: list[dict], targets: dict | None) -> None:
    policy.require(actor, "routing.manage")
    existing = {r.id: r for r in db.execute(select(RoutingRule).where(RoutingRule.institution_id == institution_id)).scalars()}
    keep = set()
    teams = {t.id for t in db.execute(select(Team).where(Team.institution_id == institution_id)).scalars()}
    # Only this institution's active officers/managers can be named as a routing target.
    receivers = {m.user_id for m, u in db.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                                                  .where(Membership.institution_id == institution_id,
                                                         User.status == "ACTIVE")).all()
                 if set(m.roles) & {"OFFICER", "MANAGER"}}
    for i, r in enumerate(rules):
        team_id = uuid.UUID(r["target_team_id"]) if r.get("target_team_id") else None
        if team_id and team_id not in teams:
            raise ValidationFailed("Unknown team.")
        user_id = uuid.UUID(r["target_user_id"]) if r.get("target_user_id") else None
        if user_id and user_id not in receivers:
            raise ValidationFailed("A routing rule can only name an active officer or manager of your institution.",
                                   code="UNKNOWN_ASSIGNEE")
        rid = uuid.UUID(r["id"]) if r.get("id") else None
        row = existing.get(rid) if rid else None
        if row is None:
            row = RoutingRule(institution_id=institution_id)
            db.add(row)
        row.priority, row.name, row.conditions = (i + 1) * 10, r.get("name") or f"Rule {i + 1}", r.get("conditions") or {}
        row.target_team_id = team_id
        row.target_user_id = user_id
        row.active = r.get("active", True)
        db.flush()
        keep.add(row.id)
    for rid, row in existing.items():
        if rid not in keep:
            db.delete(row)
    if targets:
        st = db.get(ServiceTarget, institution_id) or ServiceTarget(institution_id=institution_id)
        st.ack_within_minutes = int(targets.get("ack_within_minutes", st.ack_within_minutes or 120))
        st.first_contact_within_minutes = int(targets.get("first_contact_within_minutes",
                                                          st.first_contact_within_minutes or 1440))
        st.escalate_after_minutes = int(targets.get("escalate_after_minutes", st.escalate_after_minutes or 2880))
        db.merge(st)
    audit(db, actor, "routing.saved", "institution", institution_id, after={"rules": len(rules), "targets": targets})
    emit(db, "RoutingRulesChanged", topic="institution", aggregate_type="institution", aggregate_id=institution_id,
         institution_id=institution_id, data={"rules": len(rules)})


def save_notification_prefs(db: Session, actor: Actor, institution_id: uuid.UUID, prefs: list[dict],
                            user_id: uuid.UUID | None = None) -> None:
    clean, seen = [], set()
    for p in prefs:
        event = str(p.get("event_type") or "").strip()
        if not event or len(event) > 60 or not event.isalnum():
            raise ValidationFailed("Each preference needs a valid event type.", code="INVALID_PREF")
        if event in seen:
            raise ValidationFailed(f"{event} is listed twice.", code="INVALID_PREF")
        if p.get("min_priority", "NORMAL") not in PRIORITIES:
            raise ValidationFailed("Priority must be NORMAL, HIGH or URGENT.", code="INVALID_PREF")
        seen.add(event)
        # in_app is always on: alerts can't be silenced entirely
        channels = ["in_app", *[c for c in p.get("channels", []) if c in ("email", "sms") and c != "in_app"]]
        clean.append((event, list(dict.fromkeys(channels)), p.get("min_priority", "NORMAL"), bool(p.get("digest"))))
    who = NotificationPref.user_id.is_(None) if user_id is None else NotificationPref.user_id == user_id
    for row in db.execute(select(NotificationPref).where(NotificationPref.institution_id == institution_id, who)).scalars():
        db.delete(row)
    db.flush()
    for event, channels, priority, digest in clean:
        db.add(NotificationPref(institution_id=institution_id, user_id=user_id, event_type=event, channels=channels,
                                min_priority=priority, digest=digest))
    audit(db, actor, "notifications.saved", "institution", institution_id, after={"count": len(prefs)})


def default_notification_prefs() -> list[dict]:
    return [{"event_type": e, "channels": ["in_app", "email"] if e in ("ServiceTargetBreached", "HighMatchOpportunity")
             else ["in_app"], "min_priority": "NORMAL", "digest": e == "DailyBrief"} for e in DEFAULT_NOTIFICATION_EVENTS]
