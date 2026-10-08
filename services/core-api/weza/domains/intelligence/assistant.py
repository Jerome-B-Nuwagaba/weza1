"""Conversational Institutional AI (FSD §32, TSD §35–36; blueprint 07 §3).

User question → Authentication/RBAC → Intent → Approved WEZA tool → Structured result → explanation.
Tools are read-only, each re-checks tenant and permission, and the loop is bounded (max 3 tool calls).
With no AI available, a deterministic intent router answers from the same tools (TSD §76)."""

import json
import logging
import re
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.appetite.models import Appetite, AppetiteVersion
from weza.domains.intelligence import ai, insights, parsing
from weza.domains.matching import engine
from weza.domains.matching.rules import fmt_money
from weza.domains.misc_models import AiCallLog, LoopMetric
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import Opportunity, Outcome
from weza.domains.product.models import Product, ProductVersion
from weza.domains.trust import policy
from weza.domains.trust.service import audit
from weza.platform.context import Actor, correlation_id

log = logging.getLogger("weza.assistant")
MAX_TOOL_CALLS = 3


# ------------------------------------------------------------------ tools (allow-listed, PDP-checked)


def search_opportunities(db: Session, actor: Actor, sector: str | None = None, min_match: int | None = None,
                         customer_type: str | None = None, limit: int = 5) -> dict:
    policy.require(actor, "opportunity.read_meta")
    q = insights._scope(db, actor).where(Opportunity.state.in_(list(opp_svc.OPEN_STATES)))
    if sector:
        q = q.where(Opportunity.sector == sector)
    if customer_type:
        q = q.where(Opportunity.customer_type == customer_type)
    if min_match:
        q = q.where(Opportunity.match_score >= min_match)
    rows = db.execute(q.order_by(Opportunity.match_score.desc(), Opportunity.amount.desc()).limit(min(limit, 10))).scalars()
    return {"opportunities": [{k: v for k, v in opp_svc.summary(db, o).items()
                               if k in ("reference", "amount", "need", "sector", "district", "match_score", "state",
                                        "owner", "next_action", "id")} for o in rows]}


def get_demand_summary(db: Session, actor: Actor) -> dict:
    policy.require(actor, "analytics.read")
    d = insights.demand_intelligence(db, actor.institution_id)
    return {k: d[k] for k in ("total_needs", "total_value", "by_region", "by_sector", "by_purpose", "ticket_sizes")}


def get_near_match_analysis(db: Session, actor: Actor) -> dict:
    policy.require(actor, "analytics.read")
    r = engine.radius(db, actor.institution_id)
    return {"appetites": [{k: a[k] for k in ("appetite", "inside", "near", "outside", "near_miss_reasons")}
                          for a in r["appetites"]]}


def get_product_performance(db: Session, actor: Actor) -> dict:
    policy.require(actor, "analytics.read")
    out = []
    for p in db.execute(select(Product).where(Product.institution_id == actor.institution_id)).scalars():
        opps = db.execute(select(Opportunity).where(Opportunity.product_id == p.id)).scalars().all()
        outs = db.execute(select(Outcome).where(Outcome.opportunity_id.in_([o.id for o in opps]))).scalars().all() if opps else []
        out.append({"product": p.name, "status": p.status, "opportunities": len(opps),
                    "avg_match": round(sum(o.match_score for o in opps) / len(opps)) if opps else None,
                    "reported_approved": sum(1 for o in outs if o.state == "REPORTED_APPROVED"),
                    "reported_declined": sum(1 for o in outs if o.state == "REPORTED_DECLINED"),
                    "reported_disbursed": sum(1 for o in outs if o.state == "REPORTED_DISBURSED")})
    return {"products": out}


def get_team_queue(db: Session, actor: Actor) -> dict:
    policy.require(actor, "opportunity.read_meta")
    from weza.domains.opportunity.models import Assignment
    rows = db.execute(insights._scope(db, actor).where(Opportunity.state.in_(list(opp_svc.OPEN_STATES)))).scalars().all()
    by_owner: dict[str, int] = {}
    unassigned = 0
    for o in rows:
        a = db.get(Assignment, o.id)
        if a and a.user_id:
            s = opp_svc.summary(db, o, a)
            by_owner[s["owner"] or "?"] = by_owner.get(s["owner"] or "?", 0) + 1
        else:
            unassigned += 1
    return {"open": len(rows), "unassigned": unassigned, "by_owner": by_owner}


def simulate_appetite(db: Session, actor: Actor, field: str, op: str, value: Any) -> dict:
    """Dry-run: apply one criterion change to the first active appetite and compare. Never saves anything."""
    policy.require(actor, "appetite.simulate")
    row = db.execute(select(Appetite, AppetiteVersion).join(AppetiteVersion, AppetiteVersion.id == Appetite.active_version_id)
                     .where(Appetite.institution_id == actor.institution_id, Appetite.lifecycle_status == "ACTIVE")
                     .limit(1)).first()
    if row is None:
        return {"error": "No active appetite to simulate against."}
    ap, av = row
    pvs = [db.get(ProductVersion, p.active_version_id) for p in db.execute(
        select(Product).where(Product.id.in_(av.product_ids or []))).scalars() if p.active_version_id]
    base = engine.simulate(db, actor.institution_id, product_versions=pvs, criteria=av.criteria,
                           min_match_score=av.min_match_score)
    changed = [c for c in av.criteria if c["field"] != field] + [{"field": field, "op": op, "value": value,
                                                                  "label": None, "weight": 1, "must": True}]
    alt = engine.simulate(db, actor.institution_id, product_versions=pvs, criteria=changed,
                          min_match_score=av.min_match_score)
    return {"appetite": ap.name, "change": {"field": field, "op": op, "value": value},
            "current": {"inside": base["inside"], "near": base["near"]},
            "simulated": {"inside": alt["inside"], "near": alt["near"]},
            "note": "Simulation only. Nothing was changed — appetite changes require approval in Appetite Studio."}


TOOLS = {
    "search_opportunities": (search_opportunities, "Find the institution's best open opportunities. Optional: sector, "
                             "min_match (0-100), customer_type (SME|SALARIED|AGRICULTURE), limit.",
                             {"sector": {"type": "string"}, "min_match": {"type": "integer"},
                              "customer_type": {"type": "string"}, "limit": {"type": "integer"}}),
    "get_demand_summary": (get_demand_summary, "Aggregated WEZA demand by region, sector, purpose and ticket size.", {}),
    "get_near_match_analysis": (get_near_match_analysis, "Demand inside, near and outside the institution's appetite, "
                                "with the criteria most often missed.", {}),
    "get_product_performance": (get_product_performance, "Opportunities and reported outcomes per product.", {}),
    "get_team_queue": (get_team_queue, "Open opportunities by owner and unassigned count.", {}),
    "simulate_appetite": (simulate_appetite, "Dry-run one appetite criterion change, e.g. field=business_age_months "
                          "op=gte value=24. Never saves.", {"field": {"type": "string"}, "op": {"type": "string"},
                                                            "value": {}}),
}


def run_tool(db: Session, actor: Actor, name: str, args: dict) -> dict:
    fn = TOOLS[name][0]
    allowed = set(TOOLS[name][2])
    return fn(db, actor, **{k: v for k, v in (args or {}).items() if k in allowed})


# ------------------------------------------------------------------ deterministic router


def _route(question: str) -> list[tuple[str, dict]]:
    q = question.lower()
    sector, _ = parsing.parse_sector(q)
    ctype, c = parsing.parse_customer_type(q)
    if "simulat" in q or "what if" in q or "lower" in q or "reduce" in q:
        months = parsing.parse_months(q)
        if "business age" in q or "operating" in q or ("age" in q and months):
            return [("simulate_appetite", {"field": "business_age_months", "op": "gte", "value": months or 12})]
        amt, conf = parsing.parse_amount(q)
        if "turnover" in q and amt:
            return [("simulate_appetite", {"field": "monthly_turnover", "op": "gte", "value": float(amt)})]
        return [("get_near_match_analysis", {})]
    if "outside" in q or "near" in q or ("why" in q and ("no " in q or "not" in q)):
        return [("get_near_match_analysis", {}), ("get_demand_summary", {})]
    if "where" in q and "demand" in q or "demand" in q:
        return [("get_demand_summary", {})]
    if "product" in q and ("perform" in q or "doing" in q):
        return [("get_product_performance", {})]
    if "team" in q or "queue" in q or "unassigned" in q or "workload" in q:
        return [("get_team_queue", {})]
    return [("search_opportunities", {"sector": sector, "customer_type": ctype if c >= 0.8 else None,
                                      "min_match": 75 if "best" in q or "top" in q else None})]


def _render(name: str, r: dict) -> str:
    if "error" in r:
        return r["error"]
    if name == "search_opportunities":
        ops = r["opportunities"]
        if not ops:
            return "There are no open opportunities matching that right now."
        return "Your strongest open opportunities:\n" + "\n".join(
            f"• {o['reference']} — {fmt_money(o['amount'])}, {o['need'] or ''}, {o['district'] or ''}, match "
            f"{o['match_score']} ({o['next_action']})" for o in ops)
    if name == "get_demand_summary":
        top_r = ", ".join(f"{k} ({v})" for k, v in list(r["by_region"].items())[:3])
        top_s = ", ".join(f"{k} ({v})" for k, v in list(r["by_sector"].items())[:3])
        return (f"WEZA demand over the last 90 days: {r['total_needs']} requests worth {fmt_money(r['total_value'])}. "
                f"Top regions: {top_r}. Top sectors: {top_s}.")
    if name == "get_near_match_analysis":
        lines = []
        for a in r["appetites"]:
            reasons = ", ".join(list(a["near_miss_reasons"])[:2]) or "—"
            lines.append(f"• {a['appetite']}: {a['inside']['count']} inside ({fmt_money(a['inside']['value'])}), "
                         f"{a['near']['count']} just outside ({fmt_money(a['near']['value'])}). Most-missed: {reasons}.")
        return "Opportunity Radius:\n" + ("\n".join(lines) or "No active appetites.")
    if name == "get_product_performance":
        return "Product performance (reported outcomes):\n" + "\n".join(
            f"• {p['product']}: {p['opportunities']} opportunities, avg match {p['avg_match']}, "
            f"{p['reported_approved']} reported approved, {p['reported_disbursed']} disbursed" for p in r["products"])
    if name == "get_team_queue":
        owners = ", ".join(f"{k}: {v}" for k, v in r["by_owner"].items()) or "none assigned"
        return f"{r['open']} open opportunities; {r['unassigned']} unassigned. By owner: {owners}."
    if name == "simulate_appetite":
        c, s = r["current"], r["simulated"]
        return (f"Simulation for '{r['appetite']}' with {r['change']['field']} {r['change']['op']} "
                f"{r['change']['value']}: inside appetite would go from {c['inside']['count']} "
                f"({fmt_money(c['inside']['value'])}) to {s['inside']['count']} ({fmt_money(s['inside']['value'])}). "
                + r["note"])
    return json.dumps(r)[:800]


# ------------------------------------------------------------------ entry point


def ask(db: Session, actor: Actor, question: str) -> dict:
    question = question.strip()[:500]
    audit(db, actor, "assistant.query", "assistant", actor.institution_id, after={"length": len(question)})
    db.add(LoopMetric(loop="institution_assistant", event="ENTER", subject=str(actor.id)))
    if ai.effective_mode(db) == "AVAILABLE":
        try:
            return _ask_claude(db, actor, question)
        except Exception:  # noqa: BLE001 — fall back to deterministic routing
            log.warning("assistant_ai_failed")
            db.add(LoopMetric(loop="institution_assistant", event="FALLBACK", subject=str(actor.id)))
    calls = []
    answer_parts = []
    for name, args in _route(question)[:MAX_TOOL_CALLS]:
        try:
            r = run_tool(db, actor, name, args)
        except Exception as exc:  # noqa: BLE001 — permission or data errors become a safe message
            r = {"error": getattr(exc, "message", "That information isn't available to your role.")}
        calls.append({"tool": name, "args": args, "result": r})
        answer_parts.append(_render(name, r))
    db.add(LoopMetric(loop="institution_assistant", event="COMPLETE", subject=str(actor.id), value=len(calls)))
    return {"answer": "\n\n".join(answer_parts), "tool_calls": calls, "mode": "deterministic",
            "note": "Read-only. WEZA's assistant never changes products, appetite or assignments."}


def _ask_claude(db: Session, actor: Actor, question: str) -> dict:
    p = ai.provider()
    client, model = p.client, p.model
    tools = [{"name": n, "description": d, "input_schema": {"type": "object", "properties": props,
                                                            "additionalProperties": False}}
             for n, (_, d, props) in TOOLS.items()]
    system = ("You are WEZA's institutional assistant for a financial institution's staff. Answer only from the "
              "results of the tools provided; do not invent figures. You are read-only: you cannot change products, "
              "appetite, assignments or credit decisions, and you never claim to approve or decline credit. Keep "
              "answers short, with the key numbers. Amounts are in UGX.")
    messages: list[dict] = [{"role": "user", "content": question}]
    calls = []
    started = time.monotonic()
    tin = tout = 0
    for _ in range(MAX_TOOL_CALLS + 1):
        resp = client.messages.create(model=model, max_tokens=2048, system=system, tools=tools, messages=messages,
                                      output_config={"effort": "low"})
        tin += resp.usage.input_tokens or 0
        tout += resp.usage.output_tokens or 0
        if resp.stop_reason == "refusal":
            raise RuntimeError("refusal")
        if resp.stop_reason != "tool_use" or len(calls) >= MAX_TOOL_CALLS:
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            db.add(AiCallLog(capability="answer_institution_query", prompt_version="p1", schema_version="v1",
                             provider="anthropic", model=model, mode="AVAILABLE",
                             latency_ms=int((time.monotonic() - started) * 1000), input_tokens=tin, output_tokens=tout,
                             cost_usd=round(tin / 1e6 * ai.PRICE_IN + tout / 1e6 * ai.PRICE_OUT, 6),
                             subject=str(actor.id), correlation_id=correlation_id()))
            return {"answer": text or "I couldn't find an answer from the available data.", "tool_calls": calls,
                    "mode": "ai", "note": "Read-only. WEZA's assistant never changes products, appetite or assignments."}
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            if b.name not in TOOLS:
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": "Unknown tool", "is_error": True})
                continue
            try:
                r = run_tool(db, actor, b.name, b.input if isinstance(b.input, dict) else {})
                calls.append({"tool": b.name, "args": b.input, "result": r})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(r, default=str)[:20000]})
            except Exception as exc:  # noqa: BLE001
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                "content": getattr(exc, "message", "Not permitted for this user.")})
        messages.append({"role": "user", "content": results})
    raise RuntimeError("tool budget exhausted")


_ = (re, get_settings)
