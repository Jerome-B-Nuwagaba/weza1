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

DEFAULTS = {"country:UG": UGANDA, "question_paths:UG": QUESTION_PATHS, "match_weights": MATCH_WEIGHTS,
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
