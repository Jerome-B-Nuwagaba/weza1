"""Institution Configuration Sandbox (BRD §34.7, TSD §74; Skill §55).

Tests draft or active product/appetite/routing configuration against synthetic customers generated in memory.
Synthetic data is never written to production tables, so it cannot create opportunities, notifications or
billable events."""

import random
import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.domains.admin_config import UGANDA, all_districts, get_config, region_of
from weza.domains.appetite.models import Appetite, AppetiteVersion
from weza.domains.institution.models import Institution, RoutingRule, Team
from weza.domains.matching.engine import Supply, evaluate_supply
from weza.domains.matching.models import SimulationRun
from weza.domains.matching.rules import fmt_money
from weza.domains.product.models import Product, ProductVersion
from weza.platform.context import Actor

SCENARIOS = ["typical", "high_demand_small_tickets", "large_tickets", "young_businesses", "rural_agriculture"]


def synthetic_customers(n: int = 60, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    districts = all_districts()
    out = []
    for i in range(n):
        ctype = rng.choices(["SME", "SALARIED", "AGRICULTURE"], [0.55, 0.3, 0.15])[0]
        scenario = SCENARIOS[i % len(SCENARIOS)]
        amount = {"typical": rng.choice([3, 5, 10, 20, 30, 50]), "high_demand_small_tickets": rng.choice([1, 2, 3]),
                  "large_tickets": rng.choice([80, 150, 300]), "young_businesses": rng.choice([5, 10, 15]),
                  "rural_agriculture": rng.choice([2, 5, 8])}[scenario] * 1_000_000
        if scenario == "rural_agriculture":
            ctype = "AGRICULTURE"
        district = rng.choice(districts)
        f = {"amount": amount, "tenor_months": rng.choice([6, 12, 18, 24, 36]), "customer_type": ctype,
             "district": district, "region": region_of(district), "documents": [], "phone_verified": True,
             "has_nin": rng.random() > 0.3, "monthly_repayments": rng.choice([0, 0, 200_000, 500_000])}
        if ctype == "SME":
            f.update(sector=rng.choice(list(UGANDA["sectors"])), business_registered=rng.random() > 0.35,
                     business_age_months=rng.choice([4, 8, 14, 26, 40, 72]) if scenario != "young_businesses"
                     else rng.choice([3, 6, 10]), monthly_turnover=rng.choice([1.5, 3, 6, 12, 25, 60]) * 1_000_000,
                     purpose_category=rng.choice(["working_capital", "expansion", "equipment", "stock"]))
            f["operating_months"] = f["business_age_months"]
        elif ctype == "SALARIED":
            f.update(employment_type=rng.choice(["permanent", "contract", "casual"]),
                     employment_months=rng.choice([3, 9, 18, 36, 60]),
                     monthly_income=rng.choice([0.6, 1.2, 2.5, 4, 8]) * 1_000_000,
                     purpose_category=rng.choice(["school_fees", "home_improvement", "personal", "vehicle"]))
            f["operating_months"] = f["employment_months"]
            f["debt_service_ratio"] = round(f["monthly_repayments"] / f["monthly_income"], 3)
        else:
            f.update(sector="agriculture", farm_activity=rng.choice(["crops", "dairy", "poultry", "mixed"]),
                     operating_months=rng.choice([10, 24, 48, 96]), annual_income=rng.choice([4, 9, 20, 45]) * 1_000_000,
                     purpose_category=rng.choice(["agri_inputs", "equipment", "expansion"]))
        out.append({"id": f"SYN-{i + 1:03d}", "scenario": scenario, "fields": f})
    return out


def _latest(db: Session, model, parent_field, parent_id):
    return db.execute(select(model).where(getattr(model, parent_field) == parent_id)
                      .order_by(model.version.desc()).limit(1)).scalar_one_or_none()


def run_sandbox(db: Session, actor: Actor) -> dict:
    inst = db.get(Institution, actor.institution_id)
    weights, _ = get_config(db, "match_weights")
    products = db.execute(select(Product).where(Product.institution_id == inst.id,
                                                Product.status != "ARCHIVED")).scalars().all()
    pvs = {p.id: (p, _latest(db, ProductVersion, "product_id", p.id)) for p in products}
    apps = []
    for ap in db.execute(select(Appetite).where(Appetite.institution_id == inst.id,
                                                Appetite.lifecycle_status != "ARCHIVED")).scalars():
        av = _latest(db, AppetiteVersion, "appetite_id", ap.id)
        if av:
            apps.append((ap, av))
    if not pvs or not apps:
        return {"ready": False, "message": "Configure at least one product and one appetite to use the sandbox.",
                "results": []}
    rules = db.execute(select(RoutingRule).where(RoutingRule.institution_id == inst.id, RoutingRule.active.is_(True))
                       .order_by(RoutingRule.priority)).scalars().all()
    teams = {t.id: t.name for t in db.execute(select(Team).where(Team.institution_id == inst.id)).scalars()}
    results = []
    for c in synthetic_customers():
        best = None
        for ap, av in apps:
            for pid in av.product_ids or []:
                if pid not in pvs:
                    continue
                prod, pv = pvs[pid]
                ap_copy = Appetite(id=ap.id, institution_id=inst.id, name=ap.name, capacity_state="ACTIVE")
                r = evaluate_supply(Supply(inst, prod, pv, ap_copy, av), c["fields"], [], weights)
                if best is None or (r["eligible"], r["score"]) > (best[0]["eligible"], best[0]["score"]):
                    best = (r, pv, av)
        if best is None:
            continue
        r, pv, av = best
        routed_to = None
        if r["eligible"] and r["above_threshold"]:
            for rule in rules:
                cnd = rule.conditions or {}
                f = c["fields"]
                if cnd.get("customer_types") and f["customer_type"] not in cnd["customer_types"]:
                    continue
                if cnd.get("sectors") and f.get("sector") not in cnd["sectors"]:
                    continue
                if cnd.get("regions") and f.get("region") not in cnd["regions"]:
                    continue
                if cnd.get("min_amount") is not None and f["amount"] < float(cnd["min_amount"]):
                    continue
                if cnd.get("max_amount") is not None and f["amount"] > float(cnd["max_amount"]):
                    continue
                if cnd.get("product_ids") and str(pv.product_id) not in [str(x) for x in cnd["product_ids"]]:
                    continue
                routed_to = teams.get(rule.target_team_id) or rule.name
                break
            routed_to = routed_to or "Unassigned queue"
        results.append({"synthetic_id": c["id"], "scenario": c["scenario"], "customer_type": c["fields"]["customer_type"],
                        "amount": fmt_money(c["fields"]["amount"]), "region": c["fields"]["region"],
                        "product": pv.name, "product_version": pv.version, "product_status": pv.status,
                        "appetite_version": av.version, "appetite_status": av.status,
                        "outcome": "WOULD_ROUTE" if routed_to else ("BELOW_THRESHOLD" if r["eligible"] else "EXCLUDED"),
                        "score": r["score"], "routed_to": routed_to,
                        "reasons": [x["text"] for x in r["explanation"]["excluded_by"]][:2] or
                        [x["text"] for x in r["explanation"]["matched"]][:3]})
    summary = Counter(r["outcome"] for r in results)
    db.add(SimulationRun(institution_id=inst.id, kind="SANDBOX", criteria={"synthetic": len(results)},
                         result={"summary": dict(summary)}, created_by=actor.id))
    return {"ready": True, "synthetic": True, "summary": dict(summary), "results": results,
            "note": "Synthetic customers only. Nothing here is stored as a real opportunity or billed."}


_ = uuid
