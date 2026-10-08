"""Deterministic, versioned rules engine (TSD §18). Output per rule: PASS / FAIL / UNKNOWN with required value,
observed value and a reason code. LLMs never decide rule satisfaction."""

import hashlib
import json
from typing import Any

FIELD_LABELS = {
    "amount": "Requested amount", "tenor_months": "Repayment period", "customer_type": "Customer type",
    "sector": "Sector", "district": "District", "region": "Region", "purpose_category": "Purpose",
    "business_age_months": "Business age", "monthly_turnover": "Monthly turnover",
    "business_registered": "Business registration", "employment_type": "Employment type",
    "employment_months": "Time with employer", "monthly_income": "Monthly income", "farm_activity": "Farming activity",
    "operating_months": "Operating history", "annual_income": "Annual income",
    "monthly_repayments": "Existing repayments", "debt_service_ratio": "Existing repayments vs income",
    "has_nin": "National ID provided", "documents": "Documents",
}
MONEY_FIELDS = {"amount", "monthly_turnover", "monthly_income", "annual_income", "monthly_repayments"}
MONTH_FIELDS = {"tenor_months", "business_age_months", "employment_months", "operating_months"}
OPS = {"eq", "neq", "in", "not_in", "gte", "lte", "between", "exists", "is_true", "contains"}
NEAR_MISS_TOLERANCE = 0.20


def fmt(field: str, v: Any) -> str:
    if v is None:
        return "not provided"
    if isinstance(v, list):
        return ", ".join(fmt(field, x) for x in v)
    if field in MONEY_FIELDS:
        return fmt_money(v)
    if field in MONTH_FIELDS:
        n = int(v)
        return f"{n // 12} yr{'s' if n // 12 != 1 else ''}" + (f" {n % 12} mo" if n % 12 else "") if n >= 12 else f"{n} mo"
    if field == "debt_service_ratio":
        return f"{float(v) * 100:.0f}%"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v).replace("_", " ")


def fmt_money(v: Any, currency: str = "UGX") -> str:
    v = float(v)
    if v >= 1e9:
        return f"{currency} {v / 1e9:.2f}B".replace(".00B", "B")
    if v >= 1e6:
        return f"{currency} {v / 1e6:.1f}M".replace(".0M", "M")
    if v >= 1e3:
        return f"{currency} {v / 1e3:.0f}K"
    return f"{currency} {v:,.0f}"


def describe(rule: dict) -> str:
    if rule.get("label"):
        return rule["label"]
    f, op, v = rule["field"], rule["op"], rule.get("value")
    name = FIELD_LABELS.get(f, f)
    return {
        "gte": f"{name} at least {fmt(f, v)}", "lte": f"{name} at most {fmt(f, v)}",
        "between": f"{name} between {fmt(f, v[0])} and {fmt(f, v[1])}" if isinstance(v, list) else name,
        "in": f"{name}: {fmt(f, v)}", "not_in": f"{name} not {fmt(f, v)}", "eq": f"{name} is {fmt(f, v)}",
        "neq": f"{name} is not {fmt(f, v)}", "is_true": name, "exists": f"{name} provided",
        "contains": f"{name} includes {fmt(f, v)}",
    }.get(op, name)


def evaluate(rule: dict, fields: dict) -> dict:
    f, op, req = rule["field"], rule["op"], rule.get("value")
    obs = fields.get(f)
    status, near = "UNKNOWN", False
    if op == "exists":
        status = "PASS" if obs not in (None, "", []) else "FAIL"
    elif obs is None or obs == "":
        status = "UNKNOWN"
    else:
        try:
            if op == "eq":
                status = "PASS" if str(obs).lower() == str(req).lower() else "FAIL"
            elif op == "neq":
                status = "PASS" if str(obs).lower() != str(req).lower() else "FAIL"
            elif op == "in":
                status = "PASS" if str(obs).lower() in {str(x).lower() for x in req} else "FAIL"
            elif op == "not_in":
                status = "PASS" if str(obs).lower() not in {str(x).lower() for x in req} else "FAIL"
            elif op == "gte":
                status = "PASS" if float(obs) >= float(req) else "FAIL"
                near = status == "FAIL" and float(obs) >= float(req) * (1 - NEAR_MISS_TOLERANCE)
            elif op == "lte":
                status = "PASS" if float(obs) <= float(req) else "FAIL"
                near = status == "FAIL" and float(obs) <= float(req) * (1 + NEAR_MISS_TOLERANCE)
            elif op == "between":
                lo, hi = float(req[0]), float(req[1])
                status = "PASS" if lo <= float(obs) <= hi else "FAIL"
                near = status == "FAIL" and lo * (1 - NEAR_MISS_TOLERANCE) <= float(obs) <= hi * (1 + NEAR_MISS_TOLERANCE)
            elif op == "is_true":
                status = "PASS" if obs is True else "FAIL"
            elif op == "contains":
                status = "PASS" if req in (obs or []) else "FAIL"
        except (TypeError, ValueError):
            status = "UNKNOWN"
    code = f"{f.upper()}_{ {'PASS': 'OK', 'FAIL': 'NOT_MET', 'UNKNOWN': 'MISSING'}[status] }"
    return {"field": f, "op": op, "required": req, "observed": obs, "status": status, "near": near,
            "label": describe(rule), "code": code, "weight": rule.get("weight", 1), "must": rule.get("must", False)}


def ruleset_hash(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]
