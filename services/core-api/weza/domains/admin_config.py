"""Versioned configuration: country configuration (TSD §71), question paths (FSD §6), match weights (TSD §20).

Defaults below are seeded as version 1. Admins create new versions; the active version is read at runtime,
so Uganda is configuration — not architecture.
"""

from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.domains.misc_models import ConfigVersion

UGANDA = {
    "country_code": "UG",
    "name": "Uganda",
    "currency": "UGX",
    "phone": {"prefix": "+256", "national_regex": r"^0?(7\d{8})$", "e164_regex": r"^\+2567\d{8}$",
              "example": "0772 123 456"},
    "identity_types": [{"code": "NIN", "label": "National Identification Number (NIN)",
                        "regex": r"^[CA][MF][A-Z0-9]{12}$"}],
    "regions": {
        "Central": ["Kampala", "Wakiso", "Mukono", "Masaka", "Mpigi", "Luwero", "Mityana", "Kayunga", "Entebbe"],
        "Eastern": ["Jinja", "Mbale", "Soroti", "Tororo", "Iganga", "Busia", "Kamuli"],
        "Northern": ["Gulu", "Lira", "Arua", "Kitgum", "Apac", "Nebbi"],
        "Western": ["Mbarara", "Kabarole", "Kasese", "Hoima", "Kabale", "Masindi", "Bushenyi", "Ntungamo"],
    },
    "institution_types": ["Commercial Bank", "Credit Institution", "Microfinance Deposit-taking Institution",
                          "SACCO", "Tier 4 Microfinance", "Fintech Lender", "Other"],
    "regulators": ["Bank of Uganda", "Uganda Microfinance Regulatory Authority", "Other"],
    "sectors": {
        "retail_trade": "Retail trade", "wholesale_trade": "Wholesale trade", "manufacturing": "Manufacturing",
        "agriculture": "Agriculture", "health_pharmacy": "Health & pharmacy", "education": "Education",
        "transport": "Transport & logistics", "hospitality": "Hospitality & food", "construction": "Construction",
        "services": "Professional services", "technology": "Technology", "beauty": "Salon & beauty",
        "energy_solar": "Energy & solar", "real_estate": "Real estate",
    },
    "purpose_categories": {
        "working_capital": "Working capital", "expansion": "Business expansion", "equipment": "Equipment / assets",
        "stock": "Stock / inventory", "school_fees": "School fees", "medical": "Medical costs",
        "home_improvement": "Home improvement", "vehicle": "Vehicle", "agri_inputs": "Farm inputs",
        "solar": "Solar energy", "construction": "Construction", "personal": "Personal needs",
        "startup": "Starting a business", "debt_consolidation": "Debt consolidation",
    },
    "waiting_room_days": 30,
    "freshness_days": {"attention": 3, "stale": 7, "expired": 21},
    "languages": ["en"],
    "consent_purpose": "INSTITUTION_CONTACT_FOR_FINANCING",
    "regulatory_flags": {"data_protection_act": "Data Protection and Privacy Act, 2019"},
}

_PHONE_Q = None  # phone is handled by the VERIFY_PHONE node, not by question paths

COMMON = [
    {"key": "identity.full_name", "prompt": "What is your full name?", "type": "name", "required": True},
    {"key": "identity.nin", "prompt": "What is your National ID Number (NIN)? It helps institutions process your "
     "request faster. You can reply 'skip'.", "type": "nin", "required": False},
]

# Tap-to-choose answers for money and duration questions on WhatsApp (21 Oct review: less typing). Each entry is
# (value saved, label shown); the customer may still type an exact figure. The saved value is the CONSERVATIVE end of
# the range for what the customer will be judged on: the lower bound for income, turnover and time in business (never
# claim more than they said), the upper bound for existing repayments (never understate their debt).
_M = 1_000_000
ANSWER_BANDS = {
    "business.monthly_turnover": [(0, "Under UGX 1M"), (1 * _M, "UGX 1M - 3M"), (3 * _M, "UGX 3M - 5M"),
                                  (5 * _M, "UGX 5M - 10M"), (10 * _M, "UGX 10M - 30M"), (30 * _M, "Over UGX 30M")],
    "finance.monthly_repayments": [(0, "None"), (500_000, "Up to UGX 500K"), (1 * _M, "UGX 500K - 1M"),
                                   (3 * _M, "UGX 1M - 3M"), (5 * _M, "UGX 3M - 5M"), (10 * _M, "Over UGX 5M")],
    "employment.monthly_net_income": [(0, "Under UGX 500K"), (500_000, "UGX 500K - 1M"), (1 * _M, "UGX 1M - 2M"),
                                      (2 * _M, "UGX 2M - 4M"), (4 * _M, "UGX 4M - 8M"), (8 * _M, "Over UGX 8M")],
    "farm.annual_income": [(0, "Under UGX 2M"), (2 * _M, "UGX 2M - 5M"), (5 * _M, "UGX 5M - 10M"),
                           (10 * _M, "UGX 10M - 20M"), (20 * _M, "UGX 20M - 50M"), (50 * _M, "Over UGX 50M")],
    "need.tenor_months": [(3, "3 months"), (6, "6 months"), (12, "12 months"), (18, "18 months"),
                          (24, "24 months"), (36, "36 months")],
}
_TIME_BANDS = [(0, "Under 6 months"), (6, "6 - 12 months"), (12, "1 - 2 years"), (24, "2 - 5 years"),
               (60, "5 - 10 years"), (120, "Over 10 years")]
for _key in ("business.age_months", "employment.months", "farm.operating_months"):
    ANSWER_BANDS[_key] = _TIME_BANDS

QUESTION_PATHS = {
    "SME": COMMON + [
        {"key": "business.name", "prompt": "What is the name of your business?", "type": "text", "required": True},
        {"key": "business.sector", "prompt": "Which sector is your business in?", "type": "sector", "required": True},
        {"key": "business.district", "prompt": "In which district does your business operate?", "type": "district",
         "required": True},
        {"key": "business.age_months", "prompt": "How long has the business been operating? (e.g. '3 years' or "
         "'8 months')", "type": "months", "required": True},
        {"key": "business.monthly_turnover", "prompt": "Roughly how much does the business sell in a typical month?",
         "type": "money", "required": True},
        {"key": "business.registered", "prompt": "Is the business registered (e.g. with URSB or a trading licence)?",
         "type": "yesno", "required": True},
        {"key": "finance.monthly_repayments", "prompt": "How much do you currently repay on other loans each month? "
         "Reply 0 if none.", "type": "money", "required": True},
        {"key": "need.tenor_months", "prompt": "Over how many months would you like to repay?", "type": "months",
         "required": False},
    ],
    "SALARIED": COMMON + [
        {"key": "employment.employer", "prompt": "Who is your employer?", "type": "text", "required": True},
        {"key": "employment.type", "prompt": "What type of employment do you have?", "type": "choice",
         "options": [["permanent", "Permanent"], ["contract", "Contract"], ["casual", "Casual"]], "required": True},
        {"key": "employment.months", "prompt": "How long have you worked there?", "type": "months", "required": True},
        {"key": "employment.monthly_net_income", "prompt": "What is your monthly take-home pay?", "type": "money",
         "required": True},
        {"key": "residence.district", "prompt": "Which district do you live in?", "type": "district", "required": True},
        {"key": "finance.monthly_repayments", "prompt": "How much do you currently repay on other loans each month? "
         "Reply 0 if none.", "type": "money", "required": True},
        {"key": "need.tenor_months", "prompt": "Over how many months would you like to repay?", "type": "months",
         "required": False},
    ],
    "AGRICULTURE": COMMON + [
        {"key": "farm.activity", "prompt": "What kind of farming do you do?", "type": "choice",
         "options": [["crops", "Crops"], ["livestock", "Livestock"], ["poultry", "Poultry"], ["dairy", "Dairy"],
                     ["fish", "Fish farming"], ["mixed", "Mixed farming"]], "required": True},
        {"key": "farm.district", "prompt": "In which district is your farm?", "type": "district", "required": True},
        {"key": "farm.operating_months", "prompt": "How long have you been farming?", "type": "months",
         "required": True},
        {"key": "farm.annual_income", "prompt": "Roughly how much does the farm earn in a year?", "type": "money",
         "required": True},
        {"key": "finance.monthly_repayments", "prompt": "How much do you currently repay on other loans each month? "
         "Reply 0 if none.", "type": "money", "required": True},
        {"key": "need.tenor_months", "prompt": "Over how many months would you like to repay?", "type": "months",
         "required": False},
    ],
}

MATCH_WEIGHTS = {"product_fit": 0.30, "appetite_fit": 0.30, "preference_fit": 0.10, "readiness": 0.15,
                 "capacity_fit": 0.15}

QUALITY_WEIGHTS = {"phone_verified": 20, "identity_captured": 15, "profile_complete": 30, "documents": 15,
                   "consistency": 10, "responsiveness": 10}

# Retention policy (TSD §70-71): how long each kind of data is kept before the retention engine deletes or anonymises it.
# Periods are days since creation, or since the customer's last activity for customer data. Audit events, the decision
# ledger, commercial events and reported outcomes are NOT listed: they follow their own legal retention. `legal_holds`
# lists customer ids whose data must be kept whatever the periods say. Production values need legal sign-off.
RETENTION = {
    "rules": {
        "otp_challenge": {"action": "DELETE", "after_days": 2},
        "rate_counter": {"action": "DELETE", "after_days": 2},
        "channel_message": {"action": "ANONYMISE", "after_days": 90},
        "conversation_message": {"action": "ANONYMISE", "after_days": 180},
        "document_file": {"action": "DELETE", "after_days": 365},
        "customer_identity": {"action": "ANONYMISE", "after_days": 730},
    },
    "legal_holds": [],
}

DEFAULTS = {"country:UG": UGANDA, "retention:UG": RETENTION, "question_paths:UG": QUESTION_PATHS, "match_weights": MATCH_WEIGHTS,
            "quality_weights": QUALITY_WEIGHTS}


def get_config(db: Session | None, key: str) -> tuple[dict, int]:
    """Active (data, version). Falls back to built-in defaults (version 1) when nothing is stored."""
    if db is not None:
        row = db.execute(select(ConfigVersion).where(ConfigVersion.key == key, ConfigVersion.active.is_(True))
                         .order_by(ConfigVersion.version.desc()).limit(1)).scalar_one_or_none()
        if row:
            return row.data, row.version
    return DEFAULTS[key], 1


def country(db: Session | None = None, code: str = "UG") -> dict:
    return get_config(db, f"country:{code}")[0]


@lru_cache
def district_index(code: str = "UG") -> dict[str, str]:
    cfg = DEFAULTS[f"country:{code}"]
    return {d.lower(): region for region, ds in cfg["regions"].items() for d in ds}


def region_of(district: str | None, code: str = "UG") -> str | None:
    if not district:
        return None
    return district_index(code).get(district.lower())


def all_districts(code: str = "UG") -> list[str]:
    cfg = DEFAULTS[f"country:{code}"]
    return [d for ds in cfg["regions"].values() for d in ds]


def publish_config(db: Session, key: str, data: dict, actor: str, note: str | None = None) -> ConfigVersion:
    current = db.execute(select(ConfigVersion).where(ConfigVersion.key == key)
                         .order_by(ConfigVersion.version.desc()).limit(1)).scalar_one_or_none()
    version = (current.version + 1) if current else 2
    for row in db.execute(select(ConfigVersion).where(ConfigVersion.key == key, ConfigVersion.active.is_(True))).scalars():
        row.active = False
    row = ConfigVersion(key=key, version=version, data=data, active=True, created_by=actor, note=note)
    db.add(row)
    db.flush()
    return row
