"""The capital mandate of an appetite version, as first-class dimensions (Goal 1 §4).

An appetite is an institution's statement of who it will lend to and how much. In WEZA V1 that
statement has six dimensions: the products it covers, the customer types it serves, the sectors it
funds, the regions (geography) it operates in, the amount range it lends, and the minimum age of
the business. Each dimension is optional — unset means "not restricted on this dimension", and the
appetite's own `criteria` decide. When a dimension *is* set it is a hard constraint, so a mandate
and its criteria can never disagree about who the institution will lend to.

The dimensions are turned into deterministic rules so the rules engine (never a language model)
decides whether a customer's need falls inside the mandate.
"""

from sqlalchemy.orm import Session

from weza.domains.admin_config import get_config
from weza.domains.matching.rules import fmt_money
from weza.platform.errors import ValidationFailed

#: The customer types a mandate may name. One per question path in the country configuration.
CUSTOMER_TYPES = ("SME", "SALARIED", "AGRICULTURE")

#: The six mandate dimensions, in the order the product specification lists them.
DIMENSIONS = ("customer_types", "sectors", "regions", "min_amount", "max_amount", "min_business_age_months")


def vocabulary(db: Session | None = None, code: str = "UG") -> dict:
    """The values a mandate may use on each dimension, from the active country configuration."""
    cfg = get_config(db, f"country:{code}")[0]
    return {"customer_types": list(CUSTOMER_TYPES), "sectors": list(cfg["sectors"]), "regions": list(cfg["regions"])}


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for v in value:
        v = str(v).strip()
        if v and v not in out:
            out.append(v)
    return out


def _money(value, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationFailed("Amounts must be numbers.", details=[{"field": field}]) from exc
    if amount < 0:
        raise ValidationFailed("Amounts cannot be negative.", details=[{"field": field}])
    return amount


def validate_mandate(db: Session | None, payload: dict) -> dict:
    """Check the six mandate dimensions and return them in the shape the model stores.

    Rejects a value that is not in the country's vocabulary rather than silently storing it: a
    mandate that names a sector WEZA does not know about would silently match nothing.
    """
    vocab = vocabulary(db)
    out: dict = {}
    for dim in ("customer_types", "sectors", "regions"):
        values = _as_list(payload.get(dim))
        allowed = set(vocab[dim])
        unknown = [v for v in values if v not in allowed]
        if unknown:
            raise ValidationFailed(f"Unknown {dim.replace('_', ' ')}: {', '.join(unknown)}.",
                                   code="UNKNOWN_MANDATE_VALUE",
                                   details=[{"field": dim, "value": v, "allowed": sorted(allowed)} for v in unknown])
        out[dim] = values
    lo = _money(payload.get("min_amount"), "min_amount")
    hi = _money(payload.get("max_amount"), "max_amount")
    if lo is not None and hi is not None and lo > hi:
        raise ValidationFailed("The minimum amount cannot be above the maximum amount.",
                               details=[{"field": "min_amount"}])
    out["min_amount"], out["max_amount"] = lo, hi
    age = payload.get("min_business_age_months")
    if age is None or age == "":
        out["min_business_age_months"] = None
    else:
        try:
            age = int(age)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed("Minimum business age must be a number of months.",
                                   details=[{"field": "min_business_age_months"}]) from exc
        if age < 0:
            raise ValidationFailed("Minimum business age cannot be negative.",
                                   details=[{"field": "min_business_age_months"}])
        out["min_business_age_months"] = age
    return out


def dimensions(av) -> dict:
    """The six mandate dimensions of an appetite version, as stored."""
    if av is None:
        return {}
    return {"customer_types": list(av.customer_types or []), "sectors": list(av.sectors or []),
            "regions": list(av.regions or []), "min_amount": av.min_amount, "max_amount": av.max_amount,
            "min_business_age_months": av.min_business_age_months}


def mandate_rules(av) -> list[dict]:
    """The mandate as hard (`must`) rules for the deterministic rules engine.

    Returns an empty list when no dimension is set, so an appetite that only uses `criteria` keeps
    behaving exactly as before.
    """
    if av is None:
        return []
    rules: list[dict] = []
    if av.customer_types:
        rules.append({"field": "customer_type", "op": "in", "value": list(av.customer_types),
                      "label": f"Customer type: {', '.join(av.customer_types)}", "weight": 1, "must": True})
    if av.sectors:
        rules.append({"field": "sector", "op": "in", "value": list(av.sectors),
                      "label": f"Sector: {', '.join(av.sectors)}", "weight": 1, "must": True})
    if av.regions:
        rules.append({"field": "region", "op": "in", "value": list(av.regions),
                      "label": f"Region: {', '.join(av.regions)}", "weight": 1, "must": True})
    if av.min_business_age_months:
        rules.append({"field": "business_age_months", "op": "gte", "value": int(av.min_business_age_months),
                      "label": f"Operating for at least {av.min_business_age_months} months",
                      "weight": 1, "must": True})
    lo = float(av.min_amount) if av.min_amount is not None else 0.0
    hi = float(av.max_amount) if av.max_amount is not None else 1e15
    if av.min_amount is not None or av.max_amount is not None:
        rules.append({"field": "amount", "op": "between", "value": [lo, hi],
                      "label": f"Amount within {fmt_money(lo)}–{fmt_money(hi)}", "weight": 1, "must": True})
    return rules
