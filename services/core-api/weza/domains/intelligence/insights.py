"""Marketplace intelligence: Command Centre briefing (FSD §22), demand intelligence (FSD §30), product gaps
(FSD §31), outcome-learning insights (FSD §35), liquidity & Market State (Skill §10, §38).
All figures come from WEZA marketplace data with k-anonymity suppression — never from bank databases."""

import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.admin_config import UGANDA
from weza.domains.appetite.models import Appetite, AppetiteVersion
from weza.domains.commercial.models import CommercialEvent
from weza.domains.institution.models import Institution
from weza.domains.intelligence import agents
from weza.domains.matching import engine
from weza.domains.matching.models import Match
from weza.domains.matching.rules import fmt_money
from weza.domains.misc_models import AiCallLog, Notification, ReviewItem
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity.models import Assignment, Insight, Opportunity, Outcome
from weza.domains.product.models import Product, ProductVersion
from weza.domains.trust import policy
from weza.platform.context import Actor
from weza.platform.db import utcnow
from weza.platform.models import EventDelivery, GraphInstance

PROGRESSING = {"INFORMATION_REQUESTED", "PROCEEDING", "SUBMITTED_TO_INSTITUTION"}


def _scope(db: Session, actor: Actor):
    q = select(Opportunity).where(Opportunity.institution_id == actor.institution_id)
    if policy.officer_only(actor):
        q = q.join(Assignment, Assignment.opportunity_id == Opportunity.id).where(Assignment.user_id == actor.id)
    return q


def command_centre(db: Session, actor: Actor) -> dict:
    now = utcnow()
    opps = list(db.execute(_scope(db, actor)).scalars())
    ids = [o.id for o in opps]
    assign = {a.opportunity_id: a for a in db.execute(select(Assignment).where(Assignment.opportunity_id.in_(ids))).scalars()} \
        if ids else {}
    day = now - timedelta(hours=24)
    month = now - timedelta(days=30)
    open_ = [o for o in opps if o.state not in ("CLOSED", "WITHDRAWN", "EXPIRED", "ROUTING_FAILED", "REPORTED_DECLINED",
                                                "REMATCH_ELIGIBLE", "REPORTED_DISBURSED")]
    new = [o for o in opps if o.qualified_at >= day]
    high = [o for o in open_ if o.match_score >= 90]
    unassigned = [o for o in open_ if not (assign.get(o.id) and assign[o.id].user_id) and not o.integrity_hold]
    waiting = [o for o in open_ if assign.get(o.id) and assign[o.id].first_contact_at is None
               and o.routed_at and o.routed_at <= now - timedelta(hours=24)]
    contacted = [o for o in opps if assign.get(o.id) and assign[o.id].first_contact_at]
    response_hours = [(assign[o.id].first_contact_at - o.routed_at).total_seconds() / 3600 for o in contacted
                      if o.routed_at and o.routed_at >= month]
    outcomes = db.execute(select(Outcome).where(Outcome.institution_id == actor.institution_id,
                                                Outcome.reported_at >= month)).scalars().all()
    approved = [o for o in outcomes if o.state == "REPORTED_APPROVED"]
    disbursed = [o for o in outcomes if o.state == "REPORTED_DISBURSED"]
    qualified_30 = [o for o in opps if o.qualified_at >= month]
    cards = {
        "new": {"label": "New opportunities (24h)", "value": len(new)},
        "qualified_demand": {"label": "Qualified demand (24h)", "value": float(sum(Decimal(o.amount) for o in new)),
                             "money": True},
        "high_match": {"label": "High match (90+)", "value": len(high)},
        "contacted": {"label": "Contacted (30d)", "value": len([o for o in contacted if o.qualified_at >= month])},
        "progressing": {"label": "Progressing", "value": len([o for o in open_ if o.state in PROGRESSING])},
        "reported_approved": {"label": "Reported approved (30d)", "value": len(approved),
                              "sub": fmt_money(sum(Decimal(o.approved_amount or 0) for o in approved))},
        "reported_disbursed": {"label": "Reported disbursed (30d)", "value": len(disbursed),
                               "sub": fmt_money(sum(Decimal(o.disbursed_amount or 0) for o in disbursed))},
        "avg_response": {"label": "Avg. time to first contact",
                         "value": round(sum(response_hours) / len(response_hours), 1) if response_hours else None,
                         "unit": "h"},
        "conversion": {"label": "Conversion to reported disbursement (30d)",
                       "value": round(100 * len(disbursed) / len(qualified_30)) if qualified_30 else None, "unit": "%"},
        "unassigned": {"label": "Unassigned", "value": len(unassigned)},
        "waiting": {"label": "Customers waiting >24h", "value": len(waiting)},
    }
    attention = []
    for o in sorted(unassigned, key=lambda x: -float(x.amount))[:5]:
        attention.append({"kind": "UNASSIGNED", "id": str(o.id), "reference": o.reference,
                          "text": f"{fmt_money(o.amount)} · {o.purpose_category or ''} · {o.district or ''} · match "
                                  f"{round(o.match_score)} — unassigned", "action": "Assign", "severity": "high"})
    for o in open_:
        a = assign.get(o.id)
        if a and a.breach_state in ("APPROACHING", "BREACHED", "ESCALATED") and a.first_contact_at is None:
            attention.append({"kind": "SERVICE_TARGET", "id": str(o.id), "reference": o.reference,
                              "text": f"{o.reference} · first contact {'overdue' if a.breach_state != 'APPROACHING' else 'due soon'}",
                              "action": "Contact", "severity": "high" if a.breach_state != "APPROACHING" else "medium"})
    for o in [x for x in open_ if x.integrity_hold][:3]:
        attention.append({"kind": "ON_HOLD", "id": str(o.id), "reference": o.reference,
                          "text": f"{o.reference} on hold pending WEZA checks", "action": "View", "severity": "low"})
    stale = [o for o in open_ if o.freshness in ("STALE", "ATTENTION_REQUIRED")]
    if stale:
        attention.append({"kind": "STALE", "text": f"{len(stale)} opportunit{'ies' if len(stale) != 1 else 'y'} "
                          "need attention (no recent activity)", "action": "Review", "severity": "medium",
                          "link": "/institution/feed?freshness=STALE"})
    briefing = _briefing(cards, len(unassigned), high, new, waiting)
    funnel = Counter(o.state for o in opps)
    no_lead = None
    if not open_ and not new:
        r = engine.radius(db, actor.institution_id)
        near_total = sum(a["near"]["value"] for a in r["appetites"])
        reasons = Counter()
        for a in r["appetites"]:
            reasons.update(a["near_miss_reasons"])
        if near_total:
            top = reasons.most_common(1)[0][0] if reasons else "one criterion"
            no_lead = {"text": f"No opportunities currently match your exact mandate. {fmt_money(near_total)} of otherwise "
                               f"relevant demand sits just outside it — most often because of: {top}.",
                       "near_value": near_total, "link": "/institution/radius"}
        else:
            no_lead = {"text": "No opportunities currently match your mandate, and little demand sits nearby. Review "
                               "Demand Intelligence to see where WEZA demand is growing.", "link": "/institution/demand"}
    return {"briefing": briefing, "cards": cards, "attention": attention[:10], "funnel": dict(funnel),
            "no_lead": no_lead, "roles": sorted(actor.roles), "generated_at": now.isoformat(),
            "active_products": active_products(db, actor), "active_mandates": active_mandates(db, actor),
            "new_opportunities": new_opportunities(new),
            "insights_open": db.execute(select(func.count()).select_from(Insight).where(
                Insight.institution_id == actor.institution_id, Insight.status == "OPEN")).scalar_one()}


def active_products(db: Session, actor: Actor) -> list[dict]:
    """Products this institution can currently offer (the Command Centre's 'active products')."""
    out = []
    for p in db.execute(select(Product).where(Product.institution_id == actor.institution_id,
                                              Product.status == "ACTIVE").order_by(Product.name)).scalars():
        pv = db.get(ProductVersion, p.active_version_id) if p.active_version_id else None
        terms = (pv.terms if pv else {}) or {}
        out.append({"id": str(p.id), "name": p.name, "family": p.family,
                    "customer_type": terms.get("customer_type"),
                    "min_amount": terms.get("min_amount"), "max_amount": terms.get("max_amount"),
                    "min_tenor_months": terms.get("min_tenor_months"),
                    "max_tenor_months": terms.get("max_tenor_months"), "status": p.status})
    return out


def active_mandates(db: Session, actor: Actor) -> list[dict]:
    """Live mandates (appetites) and the products they cover."""
    out = []
    for ap in db.execute(select(Appetite).where(Appetite.institution_id == actor.institution_id,
                                                 Appetite.lifecycle_status == "ACTIVE").order_by(Appetite.name)).scalars():
        av = db.get(AppetiteVersion, ap.active_version_id) if ap.active_version_id else None
        products = []
        if av and av.product_ids:
            products = [{"id": str(x.id), "name": x.name} for x in db.execute(
                select(Product).where(Product.id.in_(list(av.product_ids)))).scalars()]
        out.append({"id": str(ap.id), "name": ap.name, "status": ap.lifecycle_status,
                    "capacity_state": ap.capacity_state, "version": av.version if av else None,
                    "min_match_score": av.min_match_score if av else None,
                    "products": products, "criteria": (av.criteria if av else []) or [],
                    "target_count": av.target_count if av else None,
                    "fulfilled_count": ap.fulfilled_count, "fulfilled_value": float(ap.fulfilled_value or 0)})
    return out


def new_opportunities(new: list, limit: int = 10) -> list[dict]:
    """The newest matched opportunities (last 24h) for the Command Centre's 'new opportunities' section."""
    return [{"id": str(o.id), "reference": o.reference, "amount": float(o.amount),
             "match_score": round(o.match_score), "quality_score": o.quality_score,
             "purpose_category": o.purpose_category,
             "district": o.district, "customer_type": o.customer_type, "sector": o.sector,
             "state": o.state, "qualified_at": o.qualified_at.isoformat()}
            for o in sorted(new, key=lambda x: -float(x.match_score))[:limit]]


def _briefing(cards: dict, unassigned: int, high: list, new: list, waiting: list) -> str:
    if not new and not unassigned and not waiting:
        return "No new opportunities in the last 24 hours. Your queue is clear."
    parts = [f"{len(new)} new opportunit{'ies' if len(new) != 1 else 'y'} matched your active mandates in the last "
             f"24 hours — {fmt_money(cards['qualified_demand']['value'])} requested."]
    if high:
        parts.append(f"{len(high)} open opportunit{'ies exceed' if len(high) != 1 else 'y exceeds'} a 90% match.")
    if waiting:
        parts.append(f"{len(waiting)} customer{'s have' if len(waiting) != 1 else ' has'} waited over 24 hours for first contact.")
    if unassigned:
        parts.append(f"{unassigned} opportunit{'ies remain' if unassigned != 1 else 'y remains'} unassigned.")
    return " ".join(parts)


def demand_intelligence(db: Session, institution_id: uuid.UUID | None = None, days: int = 90) -> dict:
    rows = engine.demand_rows(db, days)
    region, sector, ctype, purpose, readiness, tickets = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    district = Counter()
    value_by_region: dict[str, float] = defaultdict(float)
    weekly: Counter = Counter()
    now = utcnow()
    for need, f in rows:
        r = f.get("region") or "Unknown"
        region[r] += 1
        value_by_region[r] += float(need.amount or 0)
        district[f.get("district") or "Unknown"] += 1
        sector[UGANDA["sectors"].get(f.get("sector") or "", "Unspecified")] += 1
        ctype[need.customer_type or "Unknown"] += 1
        purpose[UGANDA["purpose_categories"].get(need.purpose_category or "", "Other")] += 1
        readiness[need.readiness or "Not assessed"] += 1
        a = float(need.amount or 0)
        tickets[next(b for lo, b in [(1e8, "UGX 100M+"), (5e7, "UGX 50–100M"), (1e7, "UGX 10–50M"),
                                     (5e6, "UGX 5–10M"), (1e6, "UGX 1–5M"), (0, "Under UGX 1M")] if a >= lo)] += 1
        wk = (now - need.created_at).days // 7
        if wk < 12:
            weekly[11 - wk] += 1
    match_bands = Counter()
    if institution_id:
        for m in db.execute(select(Match).where(Match.institution_id == institution_id,
                                                Match.created_at >= now - timedelta(days=days),
                                                Match.state.in_(["RANKED", "PRESENTED", "SELECTED"]))).scalars():
            match_bands["90+" if m.score >= 90 else "75–89" if m.score >= 75 else "60–74" if m.score >= 60 else "<60"] += 1
    return {"window_days": days, "total_needs": len(rows),
            "total_value": float(sum(Decimal(n.amount or 0) for n, _ in rows)),
            "by_region": engine.suppress(region), "value_by_region": {k: v for k, v in value_by_region.items()
                                                                     if region[k] >= engine.K_ANON},
            "by_district": engine.suppress(district), "by_sector": engine.suppress(sector),
            "by_customer_type": engine.suppress(ctype), "by_purpose": engine.suppress(purpose),
            "by_readiness": engine.suppress(readiness), "ticket_sizes": engine.suppress(tickets),
            "weekly_trend": [weekly.get(i, 0) for i in range(12)], "match_bands": dict(match_bands),
            "note": f"Aggregated WEZA marketplace demand. Groups with fewer than {engine.K_ANON} customers are combined."}


def reason_signals(db: Session, institution_id: uuid.UUID, days: int = 90) -> dict:
    """Why this institution passed on previews (NOT_INTERESTED), for its near-match review. Built only from the
    non-identifiable preview payload, and every breakdown is k-anonymised."""
    from weza.domains.opportunity.models import Preview, ReasonSignal
    from weza.domains.opportunity.service import REASON_SIGNALS
    since = utcnow() - timedelta(days=days)
    rows = db.execute(select(ReasonSignal, Preview).join(Preview, Preview.id == ReasonSignal.preview_id).where(
        ReasonSignal.institution_id == institution_id, ReasonSignal.created_at >= since)).all()
    by_reason, by_sector, by_region = Counter(), Counter(), Counter()
    for sig, p in rows:
        by_reason[REASON_SIGNALS.get(sig.reason, sig.reason)] += 1
        by_sector[UGANDA["sectors"].get(p.payload.get("sector") or "", "Unspecified")] += 1
        by_region[p.payload.get("region") or "Unknown"] += 1
    total = len(rows)
    return {"window_days": days, "total": total if total >= engine.K_ANON else None,
            "by_reason": engine.suppress(by_reason) if total >= engine.K_ANON else {},
            "by_sector": engine.suppress(by_sector) if total >= engine.K_ANON else {},
            "by_region": engine.suppress(by_region) if total >= engine.K_ANON else {},
            "note": f"Reasons your team gave for passing on anonymous previews. Shown once there are at least "
                    f"{engine.K_ANON}; smaller groups are combined. Use it to review appetite — WEZA never changes "
                    "your rules."}


def product_gaps(db: Session, days: int = 90) -> list[dict]:
    """Unmet-demand clusters (L2). Decision support only — never creates products (HUMAN_PRODUCT_DECISION)."""
    since = utcnow() - timedelta(days=days)
    needs = db.execute(select(FinancialNeed).where(FinancialNeed.created_at >= since, FinancialNeed.amount.is_not(None),
                                                   FinancialNeed.customer_id.is_not(None))).scalars().all()
    clusters: dict[tuple, list[FinancialNeed]] = defaultdict(list)
    for n in needs:
        clusters[(n.purpose_category or "other", n.sector or n.customer_type or "unspecified")].append(n)
    families = Counter(p.family for p in db.execute(select(Product).where(Product.status == "ACTIVE")).scalars())
    from weza.domains.intelligence.parsing import FAMILY_BY_PURPOSE
    out = []
    for (purpose, sector), ns in clusters.items():
        unmet = [n for n in ns if n.readiness in ("NO_CURRENT_MATCH", None) or n.status in ("WAITING", "NO_CURRENT_MATCH")]
        if len(unmet) < engine.K_ANON:
            continue
        fam = FAMILY_BY_PURPOSE.get(purpose, "PERSONAL")
        coverage = len(unmet) and 1 - len(unmet) / len(ns)
        out.append({"purpose": UGANDA["purpose_categories"].get(purpose, purpose.replace("_", " ").title()),
                    "segment": UGANDA["sectors"].get(sector, sector.replace("_", " ").title()),
                    "demand_count": len(ns), "unmet_count": len(unmet),
                    "unmet_value": float(sum(Decimal(n.amount) for n in unmet)), "coverage_ratio": round(coverage, 2),
                    "active_products_in_family": families.get(fam, 0), "suggested_family": fam,
                    "median_amount": float(sorted(Decimal(n.amount) for n in unmet)[len(unmet) // 2])})
    return sorted(out, key=lambda x: -x["unmet_value"])


def outcome_insights_job(db: Session) -> int:
    """Outcome Learning Loop (L1): compare reported declines with configured appetite; never auto-changes rules."""
    since = utcnow() - timedelta(days=30)
    created = 0
    criteria_for_reason = {"INCOME_TURNOVER": {"monthly_turnover", "monthly_income", "annual_income"},
                           "AFFORDABILITY": {"debt_service_ratio", "monthly_income", "monthly_turnover"},
                           "ELIGIBILITY": {"business_age_months", "employment_months", "operating_months"},
                           "COLLATERAL": set(), "DOCUMENTATION": {"business_registered", "has_nin"}}
    rows = db.execute(select(Outcome, Opportunity).join(Opportunity, Opportunity.id == Outcome.opportunity_id)
                      .where(Outcome.state == "REPORTED_DECLINED", Outcome.reported_at >= since)).all()
    by_app: dict[uuid.UUID, list] = defaultdict(list)
    for out, opp in rows:
        if opp.appetite_id:
            by_app[opp.appetite_id].append(out)
    for app_id, outs in by_app.items():
        if len(outs) < 10:
            continue
        reasons = Counter(o.reason_category for o in outs)
        reason, n = reasons.most_common(1)[0]
        if n / len(outs) < 0.4:
            continue
        ap = db.get(Appetite, app_id)
        av = db.get(AppetiteVersion, ap.active_version_id) if ap and ap.active_version_id else None
        related = [c for c in (av.criteria if av else []) if c["field"] in criteria_for_reason.get(reason, set())]
        key = f"mismatch:{app_id}:{reason}:{utcnow():%Y-%m}"
        if db.execute(select(Insight.id).where(Insight.dedupe_key == key)).first():
            continue
        label = reason.replace("_", " ").lower()
        crit = related[0].get("label") if related else None
        evidence = {"declines": len(outs), "reason": reason, "count": n, "criterion": crit}
        fallback = f"{n} of {len(outs)} declines in the last 30 days for customers who met your configured appetite were reported as '{label}'." + (f" Your current criterion is: {crit}. Review whether it reflects how you lend today?" if crit else " Consider adding a criterion that reflects this.") + " WEZA will not change your appetite automatically."
        narrative = agents.marketplace_narrative(
            db, "narrate_insight", evidence, fallback, subject=f"appetite:{app_id}"
        )
        db.add(Insight(institution_id=ap.institution_id, kind="APPETITE_OUTCOME_MISMATCH", appetite_id=app_id,
                       dedupe_key=key,
                       title=f"{n} customers in '{ap.name}' were reported declined for {label}",
                       narrative=narrative,
                       evidence=evidence))
        created += 1
    # Low fill: target well behind at mid-campaign, with near-appetite demand available
    for ap, av in db.execute(select(Appetite, AppetiteVersion).join(AppetiteVersion, AppetiteVersion.id == Appetite.active_version_id)
                             .where(Appetite.lifecycle_status == "ACTIVE", AppetiteVersion.target_count.is_not(None))).all():
        if not av.campaign_from or not av.campaign_to:
            continue
        span = (av.campaign_to - av.campaign_from).days or 1
        elapsed = (utcnow().date() - av.campaign_from).days
        if elapsed / span < 0.5 or ap.fulfilled_count >= 0.25 * av.target_count:
            continue
        key = f"lowfill:{ap.id}:{utcnow():%Y-%m}"
        if db.execute(select(Insight.id).where(Insight.dedupe_key == key)).first():
            continue
        evidence = {"fulfilled": ap.fulfilled_count, "target": av.target_count,
                    "campaign_elapsed_share": round(elapsed / span, 2)}
        fallback = ("More than half the campaign period has passed. Open Opportunity Radius to see demand "
                    "just outside this mandate and simulate a change. WEZA will not change it automatically.")
        narrative = agents.marketplace_narrative(
            db, "narrate_insight", evidence, fallback, subject=f"appetite:{ap.id}"
        )
        db.add(Insight(institution_id=ap.institution_id, kind="LOW_FILL", appetite_id=ap.id, dedupe_key=key,
                       title=f"'{ap.name}' is at {ap.fulfilled_count} of {av.target_count} target opportunities",
                       narrative=narrative,
                       evidence=evidence))
        created += 1
    return created


def liquidity(db: Session) -> list[dict]:
    """Segment liquidity (Skill §38): share of active demand that currently has a ready match."""
    needs = db.execute(select(FinancialNeed).where(FinancialNeed.status.in_(engine.SIMULATION_DEMAND),
                                                   FinancialNeed.customer_id.is_not(None))).scalars().all()
    seg: dict[tuple, list] = defaultdict(list)
    for n in needs:
        seg[(n.customer_type or "Unknown", n.region or "Unknown")].append(n)
    out = []
    for (ct, rg), ns in seg.items():
        matched = sum(1 for n in ns if n.readiness == "READY_NOW" or n.status in ("SUBMITTED", "TRACKING", "CONSENTED"))
        share = matched / len(ns)
        state = "HIGH" if share >= 0.6 else "MEDIUM" if share >= 0.35 else "LOW" if share > 0 else "ILLIQUID"
        out.append({"customer_type": ct, "region": rg, "demand": len(ns), "matched": matched,
                    "matched_share": round(share, 2), "liquidity": state,
                    "value": float(sum(Decimal(n.amount or 0) for n in ns))})
    return sorted(out, key=lambda x: (x["matched_share"], -x["demand"]))


def market_state(db: Session) -> dict:
    """Market State (Skill §10) — answers what demand, supply, appetite, capacity and gaps exist now."""
    now = utcnow()
    needs = db.execute(select(FinancialNeed.status, FinancialNeed.readiness, FinancialNeed.amount)
                       .where(FinancialNeed.customer_id.is_not(None))).all()
    active = [n for n in needs if n.status in engine.ACTIVE_DEMAND]
    apps = db.execute(select(Appetite.capacity_state, func.count()).where(Appetite.lifecycle_status == "ACTIVE")
                      .group_by(Appetite.capacity_state)).all()
    opps = db.execute(select(Opportunity.state, Opportunity.freshness)).all()
    deliveries = dict(db.execute(select(EventDelivery.status, func.count()).group_by(EventDelivery.status)).all())
    routed = sum(1 for o in opps if o.state not in ("QUALIFIED", "ROUTING_FAILED"))
    failed = sum(1 for o in opps if o.state == "ROUTING_FAILED")
    ai = db.execute(select(func.count(), func.count().filter(AiCallLog.fallback_used.is_(True)))
                    .where(AiCallLog.created_at >= now - timedelta(hours=24))).one()
    return {
        "demand": {"active_needs": len(active), "active_value": float(sum(Decimal(n.amount or 0) for n in active)),
                   "ready_now": sum(1 for n in active if n.readiness == "READY_NOW"),
                   "almost_ready": sum(1 for n in active if n.readiness == "ALMOST_READY"),
                   "unmatched": sum(1 for n in active if n.readiness == "NO_CURRENT_MATCH"),
                   "waiting_room": sum(1 for n in active if n.status == "WAITING")},
        "supply": {"active_institutions": db.execute(select(func.count()).select_from(Institution)
                                                     .where(Institution.status == "ACTIVE")).scalar_one(),
                   "active_products": db.execute(select(func.count()).select_from(Product)
                                                 .where(Product.status == "ACTIVE")).scalar_one(),
                   "appetites_by_capacity": {k: v for k, v in apps}},
        "opportunities": {"by_state": dict(Counter(o.state for o in opps)),
                          "by_freshness": dict(Counter(o.freshness for o in opps)),
                          "routing_success_rate": round(routed / (routed + failed), 3) if routed + failed else None},
        "platform": {"event_deliveries": deliveries, "dead_letters": deliveries.get("DEAD", 0),
                     "notification_failures": db.execute(select(func.count()).select_from(Notification).where(
                         Notification.status.in_(["FAILED", "DEAD"]))).scalar_one(),
                     "graphs_failed": db.execute(select(func.count()).select_from(GraphInstance).where(
                         GraphInstance.status == "FAILED")).scalar_one(),
                     "open_reviews": db.execute(select(func.count()).select_from(ReviewItem).where(
                         ReviewItem.status == "OPEN")).scalar_one(),
                     "ai_calls_24h": ai[0], "ai_fallbacks_24h": ai[1]},
        "commercial": {"billable_this_month": db.execute(select(func.count()).select_from(CommercialEvent).where(
            CommercialEvent.status == "BILLABLE", CommercialEvent.billing_period == now.strftime("%Y-%m"))).scalar_one()},
        "liquidity": liquidity(db), "gaps": product_gaps(db)[:5], "generated_at": now.isoformat(),
    }
