"""WEZA Daily and WEZA Weekly intelligence briefs (FSD §34, BRD §21).

Daily: an operational briefing for the people who work the queue (administrators, managers, officers): new qualified
opportunities, requested financing, high-match leads, customers waiting, unassigned work and today's priorities.
Weekly: an executive briefing for the people who steer the institution (executives, administrators, business and
credit/risk leads): qualified demand, progression, reported approvals and disbursements, contact performance, the
strongest segment, near-appetite demand and what to review.

Each person's brief is built with THEIR scope, so an officer's brief covers only the opportunities assigned to them, never
the institution's totals. Approvals and disbursements are always labelled as reported by the institution (BR-005); a brief
never recommends loosening criteria on its own, only that someone review them (BRD §23). Delivery uses the institution's
notification preferences (the "digest" setting and the channels chosen) and is safe to run as often as you like: one brief
per person per day or week.
"""

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.identity.models import Membership, User
from weza.domains.institution.models import Institution, NotificationPref
from weza.domains.intelligence import insights
from weza.domains.matching import engine
from weza.domains.matching.rules import fmt_money
from weza.domains.notification.service import notify_institution
from weza.domains.opportunity.models import Assignment, Insight, Opportunity, Outcome
from weza.domains.trust import roles as canon
from weza.domains.trust.policy import officer_only
from weza.platform.context import Actor
from weza.platform.db import utcnow

log = logging.getLogger("weza.briefs")
EAT = timezone(timedelta(hours=3))  # East Africa Time: no daylight saving
SEND_FROM_HOUR = 7  # briefs go out from 07:00 East Africa Time
DAILY_ROLES = {"INST_ADMIN", "MANAGER", "OFFICER"}
WEEKLY_ROLES = {"EXECUTIVE", "INST_ADMIN", "BUSINESS", "CREDIT_RISK"}
PROGRESSED = {"CONTACTED", "INFORMATION_REQUESTED", "PROCEEDING", "SUBMITTED_TO_INSTITUTION", "REPORTED_APPROVED",
              "REPORTED_DISBURSED"}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def actor_for(db: Session, user: User, member: Membership) -> Actor:
    return Actor(kind="INSTITUTION_USER", id=user.id, institution_id=member.institution_id,
                 roles=canon.expand(member.roles), team_id=member.team_id, display=user.full_name)


def daily(db: Session, actor: Actor) -> dict:
    cc = insights.command_centre(db, actor)
    c = cc["cards"]
    own = officer_only(actor)
    lines = [f"{'You have' if own else 'Your institution has'} {_plural(c['new']['value'], 'new qualified opportunity', 'new qualified opportunities')}"
             f" in the last 24 hours, {fmt_money(c['qualified_demand']['value'])} requested."]
    if c["high_match"]["value"]:
        lines.append(f"{_plural(c['high_match']['value'], 'open opportunity exceeds', 'open opportunities exceed')} a 90% match.")
    if c["waiting"]["value"]:
        lines.append(f"{_plural(c['waiting']['value'], 'customer has', 'customers have')} waited over 24 hours for first contact.")
    if c["unassigned"]["value"] and not own:
        lines.append(f"{_plural(c['unassigned']['value'], 'opportunity remains', 'opportunities remain')} unassigned.")
    if len(lines) == 1 and not c["new"]["value"]:
        lines = ["Nothing new in the last 24 hours. Your queue is clear."]
    if cc["attention"]:
        lines.append("Today's priorities:")
        lines += [f"- {a['text']}" for a in cc["attention"][:5]]
    return {"title": f"WEZA Daily, {datetime.now(EAT):%a %d %b}", "body": "\n".join(lines), "link": "/institution"}


def weekly(db: Session, actor: Actor) -> dict:
    week = utcnow() - timedelta(days=7)
    inst = actor.institution_id
    opps = list(db.execute(select(Opportunity).where(Opportunity.institution_id == inst,
                                                     Opportunity.qualified_at >= week)).scalars())
    lines = [f"Qualified demand: {_plural(len(opps), 'opportunity', 'opportunities')}, "
             f"{fmt_money(sum(float(o.amount) for o in opps))} requested, in the last 7 days."]
    progressed = [o for o in opps if o.state in PROGRESSED]
    lines.append(f"Progression: {len(progressed)} of {len(opps)} have moved beyond routing." if opps
                 else "Progression: nothing to report yet.")
    outcomes = list(db.execute(select(Outcome).where(Outcome.institution_id == inst, Outcome.reported_at >= week)).scalars())
    approved = [o for o in outcomes if o.state == "REPORTED_APPROVED"]
    disbursed = [o for o in outcomes if o.state == "REPORTED_DISBURSED"]
    lines.append(f"Reported by your team: {len(approved)} approved ({fmt_money(sum(float(o.approved_amount or 0) for o in approved))}) "
                 f"and {len(disbursed)} disbursed ({fmt_money(sum(float(o.disbursed_amount or 0) for o in disbursed))}). "
                 "These are institution-reported outcomes, not credit decisions by WEZA.")
    hours = db.execute(select(func.avg(func.extract("epoch", Assignment.first_contact_at - Opportunity.routed_at) / 3600))
                       .join(Opportunity, Opportunity.id == Assignment.opportunity_id)
                       .where(Opportunity.institution_id == inst, Assignment.first_contact_at >= week,
                              Opportunity.routed_at.is_not(None))).scalar_one()
    if hours is not None:
        lines.append(f"Contact performance: {float(hours):.1f} hours on average to first contact.")
    segments = Counter((o.sector or "other").replace("_", " ") for o in opps)
    if segments:
        name, n = segments.most_common(1)[0]
        lines.append(f"Strongest segment: {name} ({_plural(n, 'opportunity', 'opportunities')}).")
    try:
        near = sum(a.get("near") or 0 for a in engine.radius(db, inst)["appetites"] if isinstance(a.get("near"), int))
    except Exception:  # noqa: BLE001 — a brief is still worth sending without this line
        log.warning("weekly_brief_radius_unavailable")
        near = 0
    if near:
        lines.append(f"Near-appetite demand: {_plural(near, 'otherwise relevant request sits', 'otherwise relevant requests sit')} "
                     "just outside your current criteria.")
    open_insights = db.execute(select(func.count()).select_from(Insight).where(
        Insight.institution_id == inst, Insight.status == "OPEN")).scalar_one()
    if open_insights:
        lines.append(f"For review: {_plural(open_insights, 'insight is', 'insights are')} waiting for a decision. "
                     "WEZA never changes your criteria by itself.")
    iso = datetime.now(EAT).isocalendar()
    return {"title": f"WEZA Weekly, week {iso.week}", "body": "\n".join(lines), "link": "/institution/reports"}


def _wants(db: Session, institution_id, user_id, event: str) -> bool:
    """Whether this person receives the digest: their own setting, else the institution's, else yes."""
    prefs = db.execute(select(NotificationPref).where(NotificationPref.institution_id == institution_id,
                                                      NotificationPref.event_type == event)).scalars().all()
    pref = next((p for p in prefs if p.user_id == user_id), None) or next((p for p in prefs if p.user_id is None), None)
    return True if pref is None else bool(pref.digest)


def send_due(db: Session, now: datetime | None = None) -> dict:
    """Send every brief that is due and not yet sent. Idempotent: a repeat run sends nothing new."""
    local = (now or datetime.now(UTC)).astimezone(EAT)
    sent = {"daily": 0, "weekly": 0}
    if local.hour < SEND_FROM_HOUR:
        return sent
    week_key = f"{local.isocalendar().year}-W{local.isocalendar().week:02d}"
    for inst in db.execute(select(Institution).where(Institution.status == "ACTIVE")).scalars():
        for user, member in db.execute(select(User, Membership).join(Membership, Membership.user_id == User.id).where(
                Membership.institution_id == inst.id, User.status == "ACTIVE")).all():
            roles = set(canon.expand(member.roles))
            actor = actor_for(db, user, member)
            kinds = []
            if roles & DAILY_ROLES and _wants(db, inst.id, user.id, "DailyBrief"):
                kinds.append(("DailyBrief", f"daily:{local:%Y-%m-%d}", daily))
            if local.weekday() == 0 and roles & WEEKLY_ROLES and _wants(db, inst.id, user.id, "WeeklyBrief"):
                kinds.append(("WeeklyBrief", f"weekly:{week_key}", weekly))
            for event, key, build in kinds:
                try:
                    brief = build(db, actor)
                    n = notify_institution(db, inst.id, event, title=brief["title"], body=brief["body"],
                                           link=brief["link"], user_ids=[user.id], dedupe=f"{key}:{inst.id}")
                except Exception:  # noqa: BLE001 — one person's brief failing never stops everyone else's
                    log.exception("brief_failed")
                    continue
                sent["daily" if event == "DailyBrief" else "weekly"] += 1 if n else 0
    return sent
