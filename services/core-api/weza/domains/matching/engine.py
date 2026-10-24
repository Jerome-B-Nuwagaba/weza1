"""Opportunity Engine & Market Clearing (FSD §10, TSD §19–24; blueprint G4/G5).

Eligibility, appetite fit, capacity, preference, readiness and ranking are computed separately and stored as
components — never collapsed into one opaque score (Skill §14). Everything here is deterministic (AL2) and
every material determination is written to the Decision Ledger.
"""

import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.domains.admin_config import get_config
from weza.domains.appetite.mandate import mandate_rules
from weza.domains.appetite.models import Appetite, AppetiteVersion, CapacityUsage
from weza.domains.customer.models import Customer, Fact, Preference
from weza.domains.customer.service import current_facts, documents_on_file, rule_fields, snapshot_profile
from weza.domains.institution.models import Institution
from weza.domains.matching.models import ClearingRun, Match, ShadowMatch, SimulationRun, WaitingEntry
from weza.domains.matching.rules import evaluate, fmt, fmt_money, ruleset_hash
from weza.domains.need.models import FinancialNeed
from weza.domains.product.models import Product, ProductVersion
from weza.domains.trust.service import record_decision
from weza.platform import metrics
from weza.platform.controls import routing_paused
from weza.platform.db import utcnow
from weza.platform.events import emit

ALGORITHM_VERSION = "match_v1"
SHADOW_ALGORITHM_VERSION = "match_v2_shadow"
MATCH_TTL_DAYS = 7
ACTIVE_DEMAND = {"READY_FOR_MATCHING", "MATCHED", "ALMOST_READY", "NO_CURRENT_MATCH", "WAITING", "CUSTOMER_SELECTED"}
SIMULATION_DEMAND = ACTIVE_DEMAND | {"CONSENTED", "SUBMITTED", "TRACKING"}
OPEN_MATCH_STATES = ["CANDIDATE", "ELIGIBLE", "RANKED", "PRESENTED", "SELECTED"]
K_ANON = 5


@dataclass
class Supply:
    institution: Institution
    product: Product
    pv: ProductVersion
    appetite: Appetite | None
    av: AppetiteVersion | None


# ------------------------------------------------------------------ supply & capacity


def window_starts(today: date) -> dict[str, date]:
    return {"DAY": today, "WEEK": today - timedelta(days=today.weekday()), "MONTH": today.replace(day=1)}


def capacity_state(db: Session, appetite: Appetite, av: AppetiteVersion) -> str:
    """ACTIVE | LIMITED | FULL | PAUSED (TSD §24). Manual override PAUSED/LIMITED wins."""
    if appetite.capacity_override in ("PAUSED", "LIMITED", "FULL"):
        return appetite.capacity_override
    limits = av.capacity_limits or {}
    if av.target_count and appetite.fulfilled_count >= av.target_count:
        return "FULL"
    if av.target_value and Decimal(appetite.fulfilled_value or 0) >= Decimal(av.target_value):
        return "FULL"
    usage = {(u.window, u.window_start): u for u in db.execute(
        select(CapacityUsage).where(CapacityUsage.appetite_id == appetite.id)).scalars()}
    worst = 0.0
    for window, start in window_starts(date.today()).items():
        u = usage.get((window, start))
        key = {"DAY": "daily_count", "WEEK": "weekly_count", "MONTH": "monthly_count"}[window]
        if limits.get(key):
            worst = max(worst, (u.count_used if u else 0) / limits[key])
        if window == "MONTH" and limits.get("monthly_value"):
            worst = max(worst, float(u.value_used if u else 0) / float(limits["monthly_value"]))
    if worst >= 1:
        return "FULL"
    if worst >= 0.8:
        return "LIMITED"
    return "ACTIVE"


def refresh_capacity(db: Session, appetite: Appetite) -> str:
    av = db.get(AppetiteVersion, appetite.active_version_id) if appetite.active_version_id else None
    if av is None:
        return appetite.capacity_state
    new = capacity_state(db, appetite, av)
    if new != appetite.capacity_state:
        old, appetite.capacity_state = appetite.capacity_state, new
        emit(db, "CapacityChanged", topic="institution", aggregate_type="appetite", aggregate_id=appetite.id,
             institution_id=appetite.institution_id, data={"from": old, "to": new})
    return new


def consume_capacity(db: Session, appetite_id: uuid.UUID, amount: Decimal) -> None:
    for window, start in window_starts(date.today()).items():
        row = db.get(CapacityUsage, (appetite_id, window, start))
        if row is None:
            row = CapacityUsage(appetite_id=appetite_id, window=window, window_start=start, count_used=0, value_used=0)
            db.add(row)
        row.count_used += 1
        row.value_used = Decimal(row.value_used or 0) + Decimal(amount)
    ap = db.get(Appetite, appetite_id)
    if ap:
        ap.fulfilled_count += 1
        ap.fulfilled_value = Decimal(ap.fulfilled_value or 0) + Decimal(amount)
        db.flush()
        refresh_capacity(db, ap)


def active_supply(db: Session, institution_id: uuid.UUID | None = None) -> list[Supply]:
    """Only ACTIVE institutions, ACTIVE products and ACTIVE appetites in campaign window (FSD-MAT-001)."""
    if routing_paused(db):
        return []
    q = (select(Institution, Product, ProductVersion)
         .join(Product, Product.institution_id == Institution.id)
         .join(ProductVersion, ProductVersion.id == Product.active_version_id)
         .where(Institution.status == "ACTIVE", Product.status == "ACTIVE", Product.synthetic.is_(False)))
    if institution_id:
        q = q.where(Institution.id == institution_id)
    rows = db.execute(q).all()
    apps = db.execute(select(Appetite, AppetiteVersion).join(AppetiteVersion, AppetiteVersion.id == Appetite.active_version_id)
                      .where(Appetite.lifecycle_status == "ACTIVE", AppetiteVersion.synthetic.is_(False))).all()
    today = date.today()
    by_product: dict[uuid.UUID, list[tuple[Appetite, AppetiteVersion]]] = defaultdict(list)
    for ap, av in apps:
        if av.campaign_from and av.campaign_from > today or av.campaign_to and av.campaign_to < today:
            continue
        for pid in av.product_ids or []:
            by_product[pid].append((ap, av))
    out = []
    for inst, prod, pv in rows:
        for ap, av in by_product.get(prod.id, []):
            out.append(Supply(inst, prod, pv, ap, av))
    return out


# ------------------------------------------------------------------ evaluation


def _pref_fit(prefs: list[str], pv: ProductVersion, inst: Institution, fields: dict) -> float:
    if not prefs:
        return 1.0
    t = pv.terms or {}
    scores = []
    for p in prefs:
        if p in ("LOWER_MONTHLY_PAYMENT", "LONGER_TENOR"):
            scores.append(1.0 if (t.get("max_tenor_months") or 0) >= 24 else 0.5)
        elif p == "SHORTER_TENOR":
            scores.append(1.0 if (t.get("min_tenor_months") or 99) <= 6 else 0.5)
        elif p == "LOW_COLLATERAL":
            scores.append(0.3 if t.get("collateral_required") else 1.0)
        elif p == "DIGITAL":
            scores.append(1.0 if t.get("digital_journey") else 0.4)
        elif p == "FAST_RESPONSE":
            scores.append(1.0 if (t.get("typical_response_hours") or 72) <= 24 else 0.5)
        elif p == "NEAR_ME":
            served = (inst.profile or {}).get("regions_served") or []
            scores.append(1.0 if not served or fields.get("region") in served else 0.3)
    return sum(scores) / len(scores) if scores else 1.0


def evaluate_supply(s: Supply, fields: dict, prefs: list[str], weights: dict) -> dict:
    """Evaluate one (product version × appetite version) against one need's fields."""
    t = s.pv.terms or {}
    implicit = [{"field": "amount", "op": "between", "value": [t.get("min_amount", 0), t.get("max_amount", 1e15)],
                 "label": f"Amount within {fmt_money(t.get('min_amount', 0))}–{fmt_money(t.get('max_amount', 0))}",
                 "public": True}]
    product_results = [evaluate(r, fields) | {"public": r.get("public", True)} for r in implicit + (s.pv.rules or [])]
    # The mandate dimensions are hard constraints: a customer outside them is not this institution's
    # business, whatever the appetite's softer criteria say.
    appetite_results = [evaluate(r, fields) | {"public": False}
                        for r in (s.av.criteria if s.av else []) + mandate_rules(s.av)]

    hard_fail = [r for r in product_results if r["status"] == "FAIL"] + \
                [r for r in appetite_results if r["status"] == "FAIL" and r["must"]]
    unknown = [r for r in product_results if r["status"] == "UNKNOWN"] + \
              [r for r in appetite_results if r["status"] == "UNKNOWN" and r["must"]]
    req_docs = [d for d in (s.pv.requirements or []) if d.get("required")]
    missing_docs = [d for d in req_docs if d["doc_type"] not in set(fields.get("documents") or [])]

    soft = [r for r in appetite_results if not r["must"]]
    if soft:
        total = sum(r["weight"] for r in soft)
        got = sum(r["weight"] * (1 if r["status"] == "PASS" else 0.5 if r["status"] == "UNKNOWN" else 0) for r in soft)
        appetite_fit = got / total if total else 1.0
    else:
        appetite_fit = 1.0
    tenor = fields.get("tenor_months")
    if tenor is None:
        tenor_fit = 0.6
    elif (t.get("min_tenor_months") or 0) <= tenor <= (t.get("max_tenor_months") or 999):
        tenor_fit = 1.0
    else:
        tenor_fit = 0.3
    docs_fit = 1 - (len(missing_docs) / len(req_docs)) if req_docs else 1.0
    product_fit = 0.6 + 0.2 * tenor_fit + 0.2 * docs_fit
    readiness = "READY" if not unknown and not missing_docs else "ALMOST"
    cap = s.appetite.capacity_state if s.appetite else "ACTIVE"
    components = {
        "product_fit": round(product_fit, 3), "appetite_fit": round(appetite_fit, 3),
        "preference_fit": round(_pref_fit(prefs, s.pv, s.institution, fields), 3),
        "readiness": 1.0 if readiness == "READY" else 0.6,
        "capacity_fit": {"ACTIVE": 1.0, "LIMITED": 0.6}.get(cap, 0.0),
    }
    score = round(100 * sum(weights[k] * v for k, v in components.items()), 1)
    eligible = not hard_fail and cap not in ("FULL", "PAUSED")
    min_score = s.av.min_match_score if s.av else 60
    near_miss = [r for r in product_results + appetite_results if r["status"] == "FAIL" and (r["near"] or not r["must"])]
    explanation = {
        "matched": [{"code": r["code"], "text": r["label"], "public": r["public"]}
                    for r in product_results + appetite_results if r["status"] == "PASS"],
        "near_miss": [{"code": r["code"], "text": r["label"], "observed": fmt(r["field"], r["observed"]),
                       "public": r["public"]} for r in near_miss],
        "outstanding": [{"code": r["code"], "text": f"Tell us your {r['label'].lower()}", "field": r["field"]}
                        for r in unknown] + [{"code": "DOC_MISSING", "text": f"Upload: {d['label']}",
                                              "doc_type": d["doc_type"]} for d in missing_docs],
        "excluded_by": [{"code": r["code"], "text": r["label"] if r["public"] else
                         "Outside this institution's current lending focus", "public": r["public"]}
                        for r in hard_fail] + ([{"code": f"CAPACITY_{cap}", "text": "Institution is not taking new "
                                                 "requests in this category right now", "public": True}]
                                               if cap in ("FULL", "PAUSED") else []),
        "min_match_score": min_score,
    }
    return {"eligible": eligible, "above_threshold": score >= min_score, "readiness": readiness, "score": score,
            "components": components, "eligibility": product_results + appetite_results,
            "explanation": explanation, "missing_docs": missing_docs, "unknown": unknown,
            "hard_fail_count": len(hard_fail), "near_count": len(near_miss),
            "ruleset_hash": ruleset_hash(s.pv.rules, s.pv.terms, s.av.criteria if s.av else None,
                                         mandate_rules(s.av) if s.av else None)}


def _shadow_score(result: dict) -> float:
    """Shadow algorithm v2: experimental weights favouring appetite fit (Skill §56). Never shown to customers."""
    c = result["components"]
    return round(100 * (0.25 * c["product_fit"] + 0.40 * c["appetite_fit"] + 0.05 * c["preference_fit"]
                        + 0.15 * c["readiness"] + 0.15 * c["capacity_fit"]), 1)


def _excluded_institutions(db: Session, need: FinancialNeed) -> set[uuid.UUID]:
    from weza.domains.opportunity.models import Opportunity
    rows = db.execute(select(Opportunity.institution_id).where(
        Opportunity.need_id == need.id,
        Opportunity.state.in_(["REPORTED_DECLINED", "REMATCH_ELIGIBLE", "WITHDRAWN"]))).scalars()
    return set(rows)


@metrics.timed("weza_matching_seconds")
def match_need(db: Session, need: FinancialNeed, *, trigger: str = "customer", clearing_run_id=None,
               supply: list[Supply] | None = None) -> dict:
    """Re-evaluate one need against current supply. Keeps still-valid matches (so a customer's selection survives a
    harmless re-run), invalidates stale ones and creates new ones (Skill §21)."""
    customer = db.get(Customer, need.customer_id) if need.customer_id else None
    if customer is None or need.amount is None or need.customer_type is None:
        return {"readiness": None, "matches": []}
    facts = {k: f.value.get("v") for k, f in current_facts(db, customer.id).items()}
    docs = documents_on_file(db, customer.id)
    fields = rule_fields(need, facts, docs, customer)
    pref = db.get(Preference, customer.id)
    prefs = list(pref.ranking) if pref and pref.ranking else []
    weights, wver = get_config(db, "match_weights")
    snapshot = snapshot_profile(db, customer.id)
    supply = supply if supply is not None else active_supply(db)
    excluded_inst = _excluded_institutions(db, need)
    now = utcnow()

    existing = {(m.product_version_id, m.appetite_version_id): m for m in db.execute(
        select(Match).where(Match.need_id == need.id, Match.state.in_(OPEN_MATCH_STATES))).scalars()}
    seen = set()
    results = []
    for s in supply:
        if s.institution.id in excluded_inst:
            continue
        r = evaluate_supply(s, fields, prefs, weights)
        key = (s.pv.id, s.av.id if s.av else None)
        seen.add(key)
        m = existing.get(key)
        state = "RANKED" if (r["eligible"] and r["above_threshold"]) else "EXCLUDED"
        if m is None:
            m = Match(need_id=need.id, institution_id=s.institution.id, product_id=s.product.id,
                      product_version_id=s.pv.id, appetite_id=s.appetite.id if s.appetite else None,
                      appetite_version_id=s.av.id if s.av else None, state=state)
            db.add(m)
        elif state == "EXCLUDED":
            m.state = "INVALIDATED"
            m.invalidated_reason = "no_longer_eligible"
            m = Match(need_id=need.id, institution_id=s.institution.id, product_id=s.product.id,
                      product_version_id=s.pv.id, appetite_id=s.appetite.id if s.appetite else None,
                      appetite_version_id=s.av.id if s.av else None, state="EXCLUDED")
            db.add(m)
        elif m.state not in ("SELECTED", "PRESENTED"):
            m.state = state
        m.eligibility, m.components, m.score = r["eligibility"], r["components"], r["score"]
        m.explanation, m.readiness, m.ruleset_hash = r["explanation"], r["readiness"], r["ruleset_hash"]
        m.algorithm_version, m.weights_version = ALGORITHM_VERSION, wver
        m.profile_snapshot_id, m.clearing_run_id = snapshot.id, clearing_run_id
        m.expires_at = now + timedelta(days=MATCH_TTL_DAYS)
        if clearing_run_id is not None:
            db.add(ShadowMatch(clearing_run_id=clearing_run_id, need_id=need.id, product_version_id=s.pv.id,
                               algorithm_version=SHADOW_ALGORITHM_VERSION, score=_shadow_score(r),
                               eligible=r["eligible"]))
        results.append((m, r))
    invalidated = 0
    for key, m in existing.items():
        if key not in seen:
            m.state = "INVALIDATED"
            m.invalidated_reason = "supply_changed"
            invalidated += 1
    db.flush()

    ranked = sorted([(m, r) for m, r in results if m.state in ("RANKED", "PRESENTED", "SELECTED")],
                    key=lambda mr: (-(mr[1]["readiness"] == "READY"), -mr[0].score, str(mr[0].id)))
    for i, (m, _) in enumerate(ranked, start=1):
        m.rank = i
    ready = [m for m, r in ranked if r["readiness"] == "READY"]
    almost = [m for m, r in ranked if r["readiness"] == "ALMOST"]
    readiness = "READY_NOW" if ready else ("ALMOST_READY" if almost else "NO_CURRENT_MATCH")
    from weza.domains.customer.service import quality_score
    req_docs = {d["doc_type"] for m, r in ranked for d in (r["missing_docs"])}
    q, qf = quality_score(db, need, customer, docs_required=len(req_docs) + len(docs & req_docs),
                          docs_present=len(docs & req_docs))
    prev = need.readiness
    need.readiness, need.quality_score, need.quality_factors = readiness, q, qf
    need.last_matched_at = now
    if need.status in ACTIVE_DEMAND or need.status in ("PROFILE_IN_PROGRESS", "PHONE_VERIFIED", "INTENT_CONFIRMED"):
        if need.status not in ("WAITING", "CUSTOMER_SELECTED"):
            need.status = {"READY_NOW": "MATCHED", "ALMOST_READY": "ALMOST_READY",
                           "NO_CURRENT_MATCH": "NO_CURRENT_MATCH"}[readiness]
    record_decision(db, "MATCHING", "need", need.id,
                    inputs={"profile_snapshot_id": str(snapshot.id), "fields": fields, "preferences": prefs,
                            "supply": len(supply), "trigger": trigger},
                    output={"readiness": readiness, "ranked": [{"match_id": str(m.id), "score": m.score,
                                                                "readiness": m.readiness} for m, _ in ranked],
                            "excluded": sum(1 for m, _ in results if m.state == "EXCLUDED"), "invalidated": invalidated},
                    ruleset_version=f"weights_v{wver}", algorithm_version=ALGORITHM_VERSION)
    if prev != readiness or trigger != "customer":
        emit(db, "NeedMatched", topic="matching", aggregate_type="need", aggregate_id=need.id,
             data={"readiness": readiness, "matches": len(ranked), "previous": prev, "trigger": trigger})
    if prev is not None and prev != readiness:
        emit(db, "CustomerReadinessUpdated", topic="matching", aggregate_type="need", aggregate_id=need.id,
             data={"readiness": readiness, "previous": prev, "trigger": trigger})
    return {"readiness": readiness, "matches": [m for m, _ in ranked], "ready": ready, "almost": almost,
            "fields": fields}


# ------------------------------------------------------------------ market clearing (G4)


def clearing_priority(need: FinancialNeed, now) -> tuple:
    """Deterministic, auditable clearing order (Skill §22): readiness, waiting time, value, age."""
    readiness_rank = {"READY_NOW": 0, "ALMOST_READY": 1}.get(need.readiness or "", 2)
    waited = (now - need.created_at).total_seconds()
    return (readiness_rank, -waited, -float(need.amount or 0), str(need.id))


def clear_market(db: Session, trigger_event: str, *, trigger_ref: str | None = None, need_ids: list | None = None,
                 limit: int = 500) -> ClearingRun:
    started = time.monotonic()
    run = ClearingRun(trigger_event=trigger_event, trigger_ref=trigger_ref, scope={"need_ids": [str(n) for n in need_ids]}
                      if need_ids else {"all_active": True}, algorithm_version=ALGORITHM_VERSION,
                      shadow_algorithm_version=SHADOW_ALGORITHM_VERSION)
    db.add(run)
    db.flush()
    q = select(FinancialNeed).where(FinancialNeed.status.in_(ACTIVE_DEMAND), FinancialNeed.customer_id.is_not(None))
    if need_ids:
        q = q.where(FinancialNeed.id.in_(need_ids))
    needs = list(db.execute(q.limit(limit)).scalars())
    now = utcnow()
    needs.sort(key=lambda n: clearing_priority(n, now))
    supply = active_supply(db)
    for ap in {s.appetite.id: s.appetite for s in supply if s.appetite}.values():
        refresh_capacity(db, ap)
    newly = 0
    created = 0
    for need in needs:
        before = need.readiness
        res = match_need(db, need, trigger=f"clearing:{trigger_event}", clearing_run_id=run.id, supply=supply)
        created += len(res["matches"])
        if before != "READY_NOW" and res["readiness"] == "READY_NOW":
            newly += 1
            w = db.get(WaitingEntry, need.id)
            if w and w.status == "OPTED_IN":
                w.status = "MATCH_FOUND"
                w.last_cleared_at = now
                emit(db, "WaitingRoomMatchFound", topic="matching", aggregate_type="need", aggregate_id=need.id,
                     data={"matches": len(res["ready"])})
    _apply_limited_capacity(db, run, needs, now)
    run.needs_evaluated, run.matches_created, run.newly_matched_needs = len(needs), created, newly
    run.finished_at = utcnow()
    run.duration_ms = int((time.monotonic() - started) * 1000)
    emit(db, "ClearingRunCompleted", topic="matching", aggregate_type="clearing_run", aggregate_id=run.id,
         data={"trigger": trigger_event, "needs": len(needs), "newly_matched": newly})
    return run


def _apply_limited_capacity(db: Session, run: ClearingRun, needs: list[FinancialNeed], now) -> None:
    """For LIMITED appetites, reserve remaining capacity for the highest-priority demand (deterministic)."""
    limited = db.execute(select(Appetite, AppetiteVersion).join(AppetiteVersion, AppetiteVersion.id == Appetite.active_version_id)
                         .where(Appetite.capacity_state == "LIMITED", Appetite.lifecycle_status == "ACTIVE")).all()
    order = {n.id: i for i, n in enumerate(needs)}
    for ap, av in limited:
        limits = av.capacity_limits or {}
        used = db.execute(select(func.coalesce(func.max(CapacityUsage.count_used), 0)).where(
            CapacityUsage.appetite_id == ap.id, CapacityUsage.window == "DAY",
            CapacityUsage.window_start == date.today())).scalar_one()
        remaining = max(1, (limits.get("daily_count") or 10) - used)
        matches = [m for m in db.execute(select(Match).where(Match.appetite_id == ap.id, Match.state == "RANKED")).scalars()
                   if m.need_id in order]
        matches.sort(key=lambda m: order[m.need_id])
        for m in matches[remaining * 2:]:
            m.state = "EXCLUDED"
            m.invalidated_reason = "capacity_reserved_for_higher_priority_demand"
        record_decision(db, "CLEARING_CAPACITY", "appetite", ap.id, inputs={"remaining": remaining,
                        "candidates": len(matches)}, output={"kept": min(len(matches), remaining * 2)},
                        algorithm_version="clearing_v1")


# ------------------------------------------------------------------ demand projection for simulation / intelligence


def demand_rows(db: Session, days: int = 90) -> list[tuple[FinancialNeed, dict]]:
    """Permitted, de-identified demand: need + rule fields only. No identity ever leaves this function."""
    since = utcnow() - timedelta(days=days)
    needs = list(db.execute(select(FinancialNeed).where(
        FinancialNeed.status.in_(SIMULATION_DEMAND), FinancialNeed.customer_id.is_not(None),
        FinancialNeed.amount.is_not(None), FinancialNeed.customer_type.is_not(None),
        FinancialNeed.created_at >= since)).scalars())
    cids = list({n.customer_id for n in needs})
    facts: dict[uuid.UUID, dict] = defaultdict(dict)
    if cids:
        for f in db.execute(select(Fact).where(Fact.customer_id.in_(cids), Fact.superseded_at.is_(None))).scalars():
            facts[f.customer_id][f.key] = f.value.get("v")
    return [(n, rule_fields(n, facts[n.customer_id], set(), True)) for n in needs]


def _band(score: float) -> str:
    return "90+" if score >= 90 else "75–89" if score >= 75 else "60–74" if score >= 60 else "<60"


def suppress(counter: Counter, k: int = K_ANON) -> dict:
    """Privacy-preserving aggregation (TSD §39): cells under k are merged into 'Other (<5 each)'."""
    out, other = {}, 0
    for key, n in counter.most_common():
        if n >= k:
            out[key] = n
        else:
            other += n
    if other >= k:
        out[f"Other (fewer than {k} each)"] = other  # merged cells below k are dropped entirely
    return out


def simulate(db: Session, institution_id: uuid.UUID, *, product_versions: list[ProductVersion], criteria: list,
             min_match_score: int, capacity_state: str = "ACTIVE", days: int = 90,
             mandate: dict | None = None) -> dict:
    """Run proposed appetite against anonymised demand (FSD-APP-002, TSD §37). Never returns identity."""
    weights, _ = get_config(db, "match_weights")
    inst = db.get(Institution, institution_id)
    fake_ap = Appetite(institution_id=institution_id, name="simulation", capacity_state=capacity_state)
    fake_av = AppetiteVersion(criteria=criteria, min_match_score=min_match_score, capacity_limits={})
    for k, v in (mandate or {}).items():
        setattr(fake_av, k, v)
    rows = demand_rows(db, days)
    inside, near, outside = [], [], []
    near_reasons: Counter = Counter()
    bands: Counter = Counter()
    region: Counter = Counter()
    sector: Counter = Counter()
    for need, fields in rows:
        best = None
        for pv in product_versions:
            prod = Product(id=pv.product_id, institution_id=institution_id, name=pv.name, family=pv.family)
            r = evaluate_supply(Supply(inst, prod, pv, fake_ap, fake_av), fields, [], weights)
            if best is None or r["score"] > best["score"]:
                best = r
        if best is None:
            continue
        val = float(need.amount or 0)
        if best["eligible"] and best["above_threshold"]:
            inside.append(val)
            bands[_band(best["score"])] += 1
            region[fields.get("region") or "Unknown"] += 1
            sector[fields.get("sector") or "unspecified"] += 1
        elif best["hard_fail_count"] <= 1 and (best["near_count"] >= 1 or best["hard_fail_count"] == 1):
            near.append(val)
            for r in best["eligibility"]:
                if r["status"] == "FAIL":
                    near_reasons[r["label"]] += 1
        else:
            outside.append(val)
    return {
        "demand_window_days": days, "demand_considered": len(rows),
        "inside": {"count": len(inside), "value": sum(inside)},
        "near": {"count": len(near), "value": sum(near)},
        "outside": {"count": len(outside), "value": sum(outside)},
        "match_bands": dict(bands),
        "near_miss_reasons": suppress(near_reasons, 1) if len(near) >= K_ANON else
        ({"Fewer than 5 near matches": len(near)} if near else {}),
        "by_region": suppress(region), "by_sector": suppress(sector),
        "note": "Indicative only — based on anonymised WEZA marketplace demand. Not a guarantee of future opportunities.",
    }


def radius(db: Session, institution_id: uuid.UUID) -> dict:
    """Opportunity Radius / no-lead intelligence for the institution's active appetites (FSD §28)."""
    apps = db.execute(select(Appetite, AppetiteVersion).join(AppetiteVersion, AppetiteVersion.id == Appetite.active_version_id)
                      .where(Appetite.institution_id == institution_id, Appetite.lifecycle_status == "ACTIVE")).all()
    out = []
    for ap, av in apps:
        pvs = [db.get(ProductVersion, p.active_version_id) for p in db.execute(
            select(Product).where(Product.id.in_(av.product_ids or []), Product.status == "ACTIVE")).scalars()
               if p.active_version_id]
        if not pvs:
            continue
        sim = simulate(db, institution_id, product_versions=pvs, criteria=av.criteria, min_match_score=av.min_match_score)
        out.append({"appetite_id": str(ap.id), "appetite": ap.name, "version": av.version, **sim})
    return {"appetites": out}


def record_simulation(db: Session, institution_id, kind: str, criteria: dict, result: dict, actor_id=None,
                      appetite_version_id=None) -> SimulationRun:
    run = SimulationRun(institution_id=institution_id, kind=kind, criteria=criteria, result=result,
                        created_by=actor_id, appetite_version_id=appetite_version_id)
    db.add(run)
    db.flush()
    return run


# ------------------------------------------------------------------ waiting room (G5)


def opt_in_waiting(db: Session, need: FinancialNeed, channel: str = "sms") -> WaitingEntry:
    cfg, _ = get_config(db, "country:UG")
    days = cfg.get("waiting_room_days", 30)
    now = utcnow()
    w = db.get(WaitingEntry, need.id)
    if w is None:
        w = WaitingEntry(need_id=need.id, customer_id=need.customer_id, expires_at=now + timedelta(days=days),
                         reconfirm_due_at=now + timedelta(days=days - 5), notify_channel=channel)
        db.add(w)
    else:
        w.status, w.expires_at = "OPTED_IN", now + timedelta(days=days)
        w.reconfirm_due_at = now + timedelta(days=days - 5)
    need.status = "WAITING"
    need.waiting_until = w.expires_at
    emit(db, "WaitingRoomOptIn", topic="customer", aggregate_type="need", aggregate_id=need.id,
         data={"expires_at": w.expires_at.isoformat()})
    return w


def describe_options(db: Session, matches: list[Match]) -> list[dict]:
    """Customer-facing option cards. Only public reasons; confidential appetite criteria are summarised."""
    out = []
    for m in matches:
        inst = db.get(Institution, m.institution_id)
        pv = db.get(ProductVersion, m.product_version_id)
        t = pv.terms or {}
        matched_public = [x["text"] for x in m.explanation.get("matched", []) if x.get("public")]
        focus = sum(1 for x in m.explanation.get("matched", []) if not x.get("public"))
        if focus:
            matched_public.append("Fits this institution's current lending focus")
        out.append({
            "match_id": str(m.id), "rank": m.rank, "institution": inst.display_name,
            "institution_type": inst.institution_type, "product": pv.name, "family": pv.family,
            "score": round(m.score), "readiness": m.readiness,
            "amount_range": f"{fmt_money(t.get('min_amount', 0))} – {fmt_money(t.get('max_amount', 0))}",
            "tenor": f"{t.get('min_tenor_months', 1)}–{t.get('max_tenor_months', 12)} months",
            "pricing": t.get("pricing_display") or "Pricing confirmed by the institution",
            "collateral_required": bool(t.get("collateral_required")),
            "digital_journey": bool(t.get("digital_journey")),
            "typical_response_hours": t.get("typical_response_hours"),
            "requirements": [d["label"] for d in (pv.requirements or [])],
            "why": matched_public[:6],
            "outstanding": [x["text"] for x in m.explanation.get("outstanding", [])],
            "components": m.components, "state": m.state, "sponsored": m.sponsored,
        })
    return out
