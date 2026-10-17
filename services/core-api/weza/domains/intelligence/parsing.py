"""Deterministic language parsing — the AI-UNAVAILABLE path (TSD §76) and the validator for AI output.

These parsers never guess silently: each returns None when unsure, and intent extraction reports a
confidence per field so low-confidence values are confirmed with the customer (TSD §10)."""

import re
from decimal import Decimal, InvalidOperation

from weza.domains.admin_config import UGANDA, all_districts

MAGNITUDES = {
    "k": 1_000, "thousand": 1_000, "m": 1_000_000, "mn": 1_000_000, "million": 1_000_000, "millions": 1_000_000,
    "mil": 1_000_000, "b": 1_000_000_000, "bn": 1_000_000_000, "billion": 1_000_000_000,
}
CURRENCY_WORDS = r"(?:ugx|ush|ushs|shs|shillings|/=)"
NUM = r"\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
AMOUNT_RE = re.compile(
    rf"(?:{CURRENCY_WORDS}\s*)?(?P<num>{NUM})\s*(?P<mag>k|thousand|mn|million|millions|mil|m|bn|billion|b)?\b\s*(?P<cur>{CURRENCY_WORDS})?",
    re.I)
NOT_MONEY_AFTER = re.compile(r"^\s*(years?|yrs?|months?|mos?|weeks?|days?|acres?|employees?|staff|people|%)", re.I)


def parse_amount(text: str, *, require_marker: bool = False) -> tuple[Decimal | None, float]:
    """Return (amount, confidence). Recognises '30 million', 'UGX 30,000,000', '30m', '500k', '1.5bn'."""
    best: tuple[Decimal | None, float] = (None, 0.0)
    for m in AMOUNT_RE.finditer(text):
        tail = text[m.end():]
        if NOT_MONEY_AFTER.match(tail) and not m.group("mag"):
            continue
        raw = re.sub(r"[,\s]", "", m.group("num"))
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        mag = (m.group("mag") or "").lower()
        if mag:
            value *= MAGNITUDES[mag]
        has_currency = bool(m.group("cur")) or bool(re.search(CURRENCY_WORDS + r"\s*$", text[:m.start()], re.I))
        conf = 0.95 if (mag or has_currency) else (0.7 if value >= 10_000 else 0.0)
        if require_marker and conf < 0.9:
            continue
        if value < 1000 and not mag:
            continue  # bare small numbers are not loan amounts
        if conf > best[1]:
            best = (value.quantize(Decimal("1")), conf)
    return best


def parse_money_answer(text: str) -> Decimal | None:
    t = text.strip().lower()
    if t in {"0", "none", "nothing", "no", "zero", "nil", "no loans", "n/a"}:
        return Decimal(0)
    value, conf = parse_amount(text)
    if value is not None:
        return value
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", text)
    if m:
        return Decimal(m.group(1)).quantize(Decimal("1"))
    return None


def parse_months(text: str, default_unit: str = "months") -> int | None:
    t = text.lower()
    total = 0.0
    found = False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|yr|months?|mos?|mo|weeks?)", t):
        n = float(num)
        if unit.startswith("y"):
            total += n * 12
        elif unit.startswith("w"):
            total += n / 4.33
        else:
            total += n
        found = True
    if found:
        return max(0, round(total))
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "a": 1, "an": 1, "half": 0.5}
    m = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|a|an|half)\s+(a\s+)?(years?|months?)", t)
    if m:
        n = words[m.group(1)]
        return round(n * 12) if m.group(3).startswith("y") else round(n)
    m = re.search(r"since\s+(19|20)(\d{2})", t)
    if m:
        from datetime import date
        year = int(m.group(1) + m.group(2))
        return max(0, (date.today().year - year) * 12)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", t)
    if m:
        n = float(m.group(1))
        return round(n * 12) if default_unit == "years" else round(n)
    return None


CUSTOMER_TYPE_WORDS = {
    "AGRICULTURE": ["farm", "farmer", "farming", "crop", "crops", "cattle", "cows", "goats", "poultry", "chicken",
                    "maize", "coffee", "beans", "dairy", "livestock", "piggery", "pigs", "fish pond", "agri",
                    "harvest", "seeds", "fertiliser", "fertilizer", "tractor"],
    "SALARIED": ["salary", "salaried", "employed", "employee", "employer", "my job", "civil servant", "teacher",
                 "nurse", "work for", "working for", "payslip", "employment"],
    "SME": ["business", "shop", "store", "pharmacy", "salon", "restaurant", "boutique", "supermarket", "company",
            "enterprise", "hardware", "clinic", "bakery", "workshop", "factory", "stock", "inventory", "customers",
            "trade", "trading", "wholesale", "retail", "kiosk", "garage", "hotel", "my school", "my sme", "sme",
            "printing", "welding", "carpentry", "mobile money", "boda"],
}
CUSTOMER_TYPE_ANSWERS = {
    "SME": ["business", "business owner", "sme", "self employed", "self-employed", "trader", "own a business"],
    "SALARIED": ["salaried", "employee", "employed", "salary", "salaried employee", "i work", "job"],
    "AGRICULTURE": ["farmer", "farming", "agriculture", "agric", "farm"],
}

SECTOR_WORDS = {
    "health_pharmacy": ["pharmacy", "drug shop", "clinic", "medical", "health", "hospital", "chemist"],
    "agriculture": ["farm", "crop", "maize", "coffee", "cattle", "poultry", "dairy", "livestock", "agri"],
    "retail_trade": ["shop", "retail", "boutique", "supermarket", "kiosk", "store", "duka"],
    "wholesale_trade": ["wholesale", "distributor", "distribution"],
    "manufacturing": ["factory", "manufactur", "production", "processing", "bakery", "milling", "welding",
                      "carpentry", "furniture"],
    "hospitality": ["restaurant", "hotel", "cafe", "bar", "catering", "food", "lodge"],
    "education": ["school", "nursery", "academy", "college", "tuition centre"],
    "transport": ["transport", "boda", "taxi", "truck", "logistics", "delivery"],
    "construction": ["construction", "building materials", "hardware", "contractor"],
    "beauty": ["salon", "barber", "beauty", "spa"],
    "energy_solar": ["solar", "energy", "power"],
    "technology": ["software", "tech", "computer", "phone repair", "printing"],
    "services": ["consult", "services", "agency", "laundry", "cleaning"],
    "real_estate": ["rental", "real estate", "property"],
}

PURPOSE_WORDS = {
    "expansion": ["expand", "expansion", "grow", "new branch", "open another", "scale", "bigger"],
    "equipment": ["equipment", "machine", "machinery", "tools", "oven", "fridge", "freezer", "tractor", "asset"],
    "stock": ["stock", "inventory", "goods", "restock", "supplies", "merchandise"],
    "working_capital": ["working capital", "operations", "running costs", "cash flow", "pay suppliers", "wages"],
    "school_fees": ["school fees", "tuition", "fees"],
    "medical": ["medical", "hospital bill", "treatment", "surgery"],
    "home_improvement": ["renovat", "home improvement", "repair my house", "roof"],
    "vehicle": ["car", "vehicle", "motorcycle", "boda", "truck", "van"],
    "agri_inputs": ["seeds", "fertili", "inputs", "feeds", "planting", "pesticide"],
    "solar": ["solar"],
    "construction": ["build", "construct", "construction", "house", "land"],
    "startup": ["start a business", "start my business", "new business", "starting"],
    "debt_consolidation": ["clear debt", "pay off", "consolidat", "clear my loan"],
    "personal": ["personal", "wedding", "emergency", "rent"],
}

PERSONAL_PURPOSES = {"school_fees", "medical", "personal", "home_improvement", "debt_consolidation"}

FAMILY_BY_PURPOSE = {
    "expansion": "SME_GROWTH", "equipment": "ASSET_FINANCE", "stock": "SME_WORKING_CAPITAL",
    "working_capital": "SME_WORKING_CAPITAL", "school_fees": "SCHOOL_FEES", "medical": "PERSONAL",
    "home_improvement": "PERSONAL", "vehicle": "ASSET_FINANCE", "agri_inputs": "AGRI_INPUTS", "solar": "ASSET_FINANCE",
    "construction": "PERSONAL", "startup": "SME_GROWTH", "debt_consolidation": "PERSONAL", "personal": "PERSONAL",
}


def _match_words(t: str, table: dict[str, list[str]]) -> tuple[str | None, float]:
    scores: dict[str, int] = {}
    for key, words in table.items():
        for w in words:
            if re.search(r"\b" + re.escape(w), t):
                scores[key] = scores.get(key, 0) + 1
    if not scores:
        return None, 0.0
    key = max(scores, key=lambda k: scores[k])
    return key, min(0.9, 0.65 + 0.1 * scores[key])


def parse_customer_type(text: str) -> tuple[str | None, float]:
    t = text.lower().strip()
    for key, answers in CUSTOMER_TYPE_ANSWERS.items():
        if t in answers:
            return key, 1.0
    return _match_words(t, CUSTOMER_TYPE_WORDS)


def parse_sector(text: str) -> tuple[str | None, float]:
    t = text.lower().strip()
    if t in UGANDA["sectors"]:
        return t, 1.0
    for code, label in UGANDA["sectors"].items():
        if t == label.lower():
            return code, 1.0
    return _match_words(t, SECTOR_WORDS)


def parse_purpose(text: str) -> tuple[str | None, str | None, float]:
    """Return (purpose_category, purpose_phrase, confidence)."""
    t = text.lower()
    cat, conf = _match_words(t, PURPOSE_WORDS)
    phrase = None
    m = re.search(r"\b(?:to|for)\s+(.{3,80}?)(?:[.!?]|$)", text, re.I)
    if m:
        phrase = m.group(1).strip()
    elif cat:
        phrase = text.strip()[:120]
    return cat, phrase, conf


def detect_district(text: str) -> str | None:
    t = text.lower()
    for d in sorted(all_districts(), key=len, reverse=True):
        if re.search(r"\b" + re.escape(d.lower()) + r"\b", t):
            return d
    if "fort portal" in t:
        return "Kabarole"
    return None


def parse_phone(text: str, cfg: dict = UGANDA) -> str | None:
    digits = re.sub(r"[^\d+]", "", text)
    if re.fullmatch(cfg["phone"]["e164_regex"], digits):
        return digits
    if digits.startswith("256") and re.fullmatch(cfg["phone"]["e164_regex"], "+" + digits):
        return "+" + digits
    m = re.fullmatch(cfg["phone"]["national_regex"], digits)
    if m:
        return cfg["phone"]["prefix"] + m.group(1)
    return None


def parse_yesno(text: str) -> bool | None:
    t = text.lower().strip().strip(".!")
    if t in {"yes", "y", "yeah", "yep", "true", "registered", "it is", "sure", "ok", "yes it is", "ndiyo", "ye"}:
        return True
    if t in {"no", "n", "nope", "false", "not registered", "not yet", "it is not"}:
        return False
    if t.startswith("yes"):
        return True
    if t.startswith("no"):
        return False
    return None


def parse_nin(text: str) -> str | None:
    t = re.sub(r"\s", "", text.upper())
    return t if re.fullmatch(UGANDA["identity_types"][0]["regex"], t) else None


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"], start=1)}


def parse_dob(text: str) -> str | None:
    """Date of birth → ISO 'YYYY-MM-DD'. Numeric dates are day-first (31/03/1993) as written in Uganda; also
    accepts 1993-03-31 and '31 March 1993' / 'March 31, 1993'. Rejects impossible and future dates."""
    import datetime as _dt
    t = (text or "").strip().lower().replace(",", " ")
    y = m = d = None
    if mt := re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t):
        y, m, d = (int(x) for x in mt.groups())
    elif mt := re.fullmatch(r"(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{4})", t):
        d, m, y = (int(x) for x in mt.groups())
    elif mt := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\s+(\d{4})", t):
        d, m, y = int(mt.group(1)), _MONTHS.get(mt.group(2)[:3]), int(mt.group(3))
    elif mt := re.fullmatch(r"([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})", t):
        m, d, y = _MONTHS.get(mt.group(1)[:3]), int(mt.group(2)), int(mt.group(3))
    if not (y and m and d):
        return None
    try:
        day = _dt.date(y, m, d)
    except ValueError:
        return None
    return day.isoformat() if 1900 <= y and day <= _dt.date.today() else None


def parse_name(text: str) -> str | None:
    t = re.sub(r"(?i)^(my name is|i am|i'm|name:)\s*", "", text.strip()).strip(" .")
    if 3 <= len(t) <= 80 and re.fullmatch(r"[A-Za-z][A-Za-z' .-]+", t) and len(t.split()) >= 2:
        return " ".join(p.capitalize() for p in t.split())
    return None


def extract_intent(text: str) -> dict:
    """Deterministic FinancialIntent v1."""
    amount, a_conf = parse_amount(text)
    ctype, c_conf = parse_customer_type(text)
    sector, s_conf = parse_sector(text)
    pcat, phrase, p_conf = parse_purpose(text)
    district = detect_district(text)
    if pcat in PERSONAL_PURPOSES and sector == "education":
        sector, s_conf = None, 0.0  # "school fees" is a purpose, not a business sector
    if pcat in PERSONAL_PURPOSES and c_conf < 0.8:
        ctype, c_conf = None, 0.0  # personal needs don't reveal customer type; ask (FSD-INT-001 example)
    if sector == "agriculture" and ctype is None:
        ctype, c_conf = "AGRICULTURE", 0.7
    if sector and sector != "agriculture" and ctype is None and pcat not in ("school_fees", "medical", "personal"):
        ctype, c_conf = "SME", 0.7
    tenor = None
    m = re.search(r"(?:over|for|within|in)\s+(\d+\s*(?:years?|months?))", text, re.I)
    if m and pcat != "school_fees":
        tenor = parse_months(m.group(1))
    urgency = "HIGH" if re.search(r"\b(urgent|urgently|asap|immediately|this week|today)\b", text, re.I) else None
    return {
        "amount": float(amount) if amount is not None else None,
        "currency": "UGX",
        "purpose": phrase,
        "purpose_category": pcat,
        "customer_type": ctype,
        "sector": sector,
        "district": district,
        "tenor_months": tenor,
        "urgency": urgency,
        "product_family": FAMILY_BY_PURPOSE.get(pcat or "", None),
        "confidence": {"amount": a_conf, "customer_type": c_conf, "sector": s_conf, "purpose": p_conf,
                       "district": 0.9 if district else 0.0},
        "source": "deterministic",
    }
