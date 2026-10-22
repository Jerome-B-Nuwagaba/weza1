"""Demo & test seed. Creates fictional institutions, users for every role, products, appetites, routing, contracts
and ~120 clearly-marked DEMO customers across the whole opportunity lifecycle — all through the real services
(sagas, events, consumers), so the demo exercises the same code paths as production.

Never runs in production (guarded). Usage: python -m weza.seed
"""

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

import weza.consumers  # noqa: F401
from weza.config import get_settings
from weza.domains.admin_config import DEFAULTS, region_of
from weza.domains.appetite import service as appetite_svc
from weza.domains.commercial.models import Contract
from weza.domains.consent import service as consent_svc
from weza.domains.customer import service as customer_svc
from weza.domains.identity import service as identity
from weza.domains.identity.models import User
from weza.domains.institution import service as inst_svc
from weza.domains.institution.models import Institution, Team
from weza.domains.intelligence import insights
from weza.domains.matching import engine
from weza.domains.misc_models import ConfigVersion
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import Activity, Assignment, Opportunity, Outcome
from weza.domains.product import service as product_svc
from weza.platform.context import Actor
from weza.platform.db import session_scope, utcnow
from weza.platform.events import drain
from weza.platform.models import FeatureFlag

DEMO_PASSWORD = "WezaDemo!2026"
FIRST = ["Grace", "Joseph", "Sarah", "Moses", "Esther", "Daniel", "Ruth", "Peter", "Agnes", "Isaac", "Brenda", "Ronald",
         "Harriet", "Emmanuel", "Doreen", "Patrick", "Juliet", "Samuel", "Prossy", "Ivan", "Florence", "Denis", "Winnie",
         "Brian", "Rebecca", "Allan", "Sylvia", "Godfrey", "Phiona", "Henry"]
LAST = ["Nakato", "Okello", "Namubiru", "Mugisha", "Achieng", "Tumusiime", "Nansubuga", "Opio", "Kyomuhendo", "Ssali",
        "Atim", "Kato", "Nabirye", "Byaruhanga", "Akello", "Wasswa", "Nakimuli", "Odongo", "Asiimwe", "Lubega"]


def _staff(db: Session, inst: Institution, domain: str, people: list[tuple[str, str, list[str], str | None]],
           teams: dict[str, uuid.UUID]) -> dict[str, User]:
    out = {}
    for key, name, roles, team in people:
        u = identity.create_user(db, email=f"{key}@{domain}", full_name=name, password=DEMO_PASSWORD,
                                 kind="INSTITUTION", institution_id=inst.id, roles=roles,
                                 team_id=teams.get(team) if team else None)
        out[key] = u
    return out


def _actor(db: Session, u: User) -> Actor:
    return identity.actor_for_user(db, u, mfa=True)


def _product(db, maker: Actor, checker: Actor, **p) -> uuid.UUID:
    pv = product_svc.create(db, maker, p)
    product_svc.submit(db, maker, pv)
    product_svc.review(db, checker, pv, True, "Approved for WEZA marketplace (demo)")
    return pv.product_id


def _appetite(db, maker: Actor, checker: Actor, **a):
    av = appetite_svc.create(db, maker, a)
    appetite_svc.simulate_version(db, maker, av)
    appetite_svc.approve(db, checker, av, True, "Mandate approved (demo)")
    return av.appetite_id


def seed_config(db: Session) -> None:
    for key, data in DEFAULTS.items():
        if not db.execute(select(ConfigVersion).where(ConfigVersion.key == key)).first():
            db.add(ConfigVersion(key=key, version=1, data=data, active=True, created_by="seed"))
    for key, on, desc in [("channel.whatsapp_simulator", True, "WhatsApp simulator"),
                          ("marketplace.preview", True, "Opportunity Preview & Institution Interest"),
                          ("matching.shadow", True, "Shadow algorithm comparison")]:
        if db.get(FeatureFlag, key) is None:
            db.add(FeatureFlag(key=key, enabled=on, description=desc))
    consent_svc.current_template(db)


def seed_weza_staff(db: Session) -> None:
    for email, name, roles in [("admin@weza.demo", "Wanjiru Admin", ["WEZA_SUPER", "WEZA_OPS", "WEZA_COMMERCIAL"]),
                               ("ops@weza.demo", "Tendo Operations", ["WEZA_OPS"]),
                               ("commercial@weza.demo", "Kevin Commercial", ["WEZA_COMMERCIAL"])]:
        identity.create_user(db, email=email, full_name=name, password=DEMO_PASSWORD, kind="WEZA", weza_roles=roles)


def seed_institutions(db: Session) -> dict:
    ops = Actor(kind="WEZA_USER", roles=frozenset({"WEZA_OPS"}), display="Tendo Operations (seed)")
    result = {}

    def make(legal, display, itype, licence, regulator, domain, desc, regions):
        inst, admin = inst_svc.apply(db, {
            "legal_name": legal, "display_name": display, "institution_type": itype, "licence_no": licence,
            "regulator": regulator, "description": desc, "accept_terms": True,
            "representative": {"name": f"{display} Representative", "email": f"rep@{domain}"},
            "compliance": {"name": f"{display} Compliance", "email": f"compliance@{domain}"},
            "admin_name": f"{display} Admin", "admin_email": f"admin@{domain}", "admin_password": DEMO_PASSWORD})
        inst.profile = {**inst.profile, "regions_served": regions}
        return inst, admin

    # ---------------- Lakeside Bank
    inst, admin = make("Lakeside Bank Uganda Limited", "Lakeside Bank", "Commercial Bank", "BOU/CB/0001-DEMO",
                       "Bank of Uganda", "lakeside.demo", "Commercial bank focused on SME growth.",
                       ["Central", "Western", "Eastern"])
    inst_svc.verify(db, ops, inst, True, "Licence and representative verified (demo)")
    t_sme, t_asset = Team(institution_id=inst.id, name="SME Team"), Team(institution_id=inst.id, name="Asset Finance Team")
    db.add_all([t_sme, t_asset])
    db.flush()
    people = _staff(db, inst, "lakeside.demo", [
        ("exec", "Amina Kato", ["EXECUTIVE"], None), ("business", "Brian Ssemanda", ["BUSINESS"], None),
        ("credit", "Clare Nankya", ["CREDIT_RISK"], None), ("manager", "Moses Opolot", ["MANAGER"], "SME Team"),
        ("officer", "Juliet Namata", ["OFFICER"], "SME Team"), ("officer2", "Paul Kiggundu", ["OFFICER"], "SME Team"),
        ("asset", "Rita Akello", ["OFFICER"], "Asset Finance Team"), ("compliance", "Henry Mutebi", ["COMPLIANCE"], None),
    ], {"SME Team": t_sme.id, "Asset Finance Team": t_asset.id})
    biz, cr, ad = _actor(db, people["business"]), _actor(db, people["credit"]), _actor(db, admin)
    p1 = _product(db, biz, cr, name="SME Growth Loan", family="SME_GROWTH",
                  terms={"min_amount": 5_000_000, "max_amount": 150_000_000, "min_tenor_months": 6,
                         "max_tenor_months": 36, "pricing_display": "From 18% p.a. (indicative)",
                         "collateral_required": False, "digital_journey": True, "typical_response_hours": 24,
                         "description": "Working capital and expansion finance for established SMEs."},
                  rules=[{"field": "customer_type", "op": "in", "value": ["SME"], "label": "Registered business owner"},
                         {"field": "business_age_months", "op": "gte", "value": 12, "label": "Operating for at least 1 year"},
                         {"field": "business_registered", "op": "is_true", "label": "Business is registered"}],
                  requirements=[{"doc_type": "business_registration", "label": "Business registration certificate",
                                 "required": False},
                                {"doc_type": "bank_statement", "label": "6-month bank statement", "required": False}])
    p2 = _product(db, biz, cr, name="Equipment & Asset Finance", family="ASSET_FINANCE",
                  terms={"min_amount": 10_000_000, "max_amount": 300_000_000, "min_tenor_months": 12,
                         "max_tenor_months": 48, "pricing_display": "From 17% p.a. (indicative)",
                         "collateral_required": True, "digital_journey": False, "typical_response_hours": 48},
                  rules=[{"field": "customer_type", "op": "in", "value": ["SME"], "label": "Business customer"},
                         {"field": "business_age_months", "op": "gte", "value": 24, "label": "Operating for 2+ years"},
                         {"field": "monthly_turnover", "op": "gte", "value": 5_000_000,
                          "label": "Monthly turnover at least UGX 5M"}],
                  requirements=[{"doc_type": "trading_licence", "label": "Trading licence", "required": True}])
    _appetite(db, cr, ad, name="Q4 SME Growth Mandate", product_ids=[str(p1), str(p2)], min_match_score=65,
              criteria=[{"field": "sector", "op": "in", "weight": 2,
                         "value": ["health_pharmacy", "retail_trade", "manufacturing", "wholesale_trade", "hospitality",
                                   "construction"], "label": "Target sectors"},
                        {"field": "region", "op": "in", "value": ["Central", "Western", "Eastern"], "weight": 1,
                         "label": "Target regions"},
                        {"field": "monthly_turnover", "op": "gte", "value": 3_000_000, "weight": 1,
                         "label": "Turnover UGX 3M+ per month"},
                        {"field": "debt_service_ratio", "op": "lte", "value": 0.5, "weight": 1,
                         "label": "Existing repayments at most 50% of capacity"}],
              target_count=200, target_value=6_000_000_000, capacity_limits={"daily_count": 60, "monthly_count": 600},
              campaign_from=str(date.today() - timedelta(days=45)), campaign_to=str(date.today() + timedelta(days=60)))
    inst_svc.save_routing(db, ad, inst.id, [
        {"name": "Large tickets → Asset Finance Team", "conditions": {"min_amount": 50_000_001},
         "target_team_id": str(t_asset.id)},
        {"name": "SME up to UGX 50M → SME Team", "conditions": {"customer_types": ["SME"], "max_amount": 50_000_000},
         "target_team_id": str(t_sme.id)}], {"ack_within_minutes": 120, "first_contact_within_minutes": 480,
                                             "escalate_after_minutes": 1440})
    inst_svc.save_notification_prefs(db, ad, inst.id, inst_svc.default_notification_prefs())
    inst_svc.activate(db, ad, inst)
    result["lakeside"] = {"inst": inst, "users": {**people, "admin": admin}}

    # ---------------- Pearl SACCO
    inst, admin = make("Pearl Teachers & Traders SACCO Ltd", "Pearl SACCO", "SACCO", "UMRA/SACCO/0412-DEMO",
                       "Uganda Microfinance Regulatory Authority", "pearl.demo",
                       "Member-owned SACCO serving salaried workers and micro-businesses.", ["Central", "Eastern"])
    inst_svc.verify(db, ops, inst, True, "Licence verified (demo)")
    t1 = Team(institution_id=inst.id, name="Member Loans")
    db.add(t1)
    db.flush()
    people = _staff(db, inst, "pearl.demo", [
        ("business", "Diana Auma", ["BUSINESS", "CREDIT_RISK"], None), ("manager", "Fred Lukwago", ["MANAGER"], "Member Loans"),
        ("officer", "Stella Nabweteme", ["OFFICER"], "Member Loans"), ("compliance", "Ali Wamala", ["COMPLIANCE"], None)],
        {"Member Loans": t1.id})
    biz, ad = _actor(db, people["business"]), _actor(db, admin)
    ps = _product(db, biz, ad, name="Salary Advance", family="SALARY_LOAN",
                  terms={"min_amount": 500_000, "max_amount": 20_000_000, "min_tenor_months": 3, "max_tenor_months": 24,
                         "pricing_display": "1.5% per month (indicative)", "collateral_required": False,
                         "digital_journey": True, "typical_response_hours": 12},
                  rules=[{"field": "customer_type", "op": "in", "value": ["SALARIED"], "label": "Salaried employee"},
                         {"field": "employment_months", "op": "gte", "value": 6, "label": "At least 6 months with employer"},
                         {"field": "monthly_income", "op": "gte", "value": 400_000, "label": "Take-home pay UGX 400K+"},
                         {"field": "debt_service_ratio", "op": "lte", "value": 0.5,
                          "label": "Existing repayments at most half of pay"}],
                  requirements=[{"doc_type": "payslip", "label": "Recent payslip", "required": False}])
    pf = _product(db, biz, ad, name="School Fees Loan", family="SCHOOL_FEES",
                  terms={"min_amount": 300_000, "max_amount": 10_000_000, "min_tenor_months": 3, "max_tenor_months": 12,
                         "pricing_display": "1.25% per month (indicative)", "collateral_required": False,
                         "digital_journey": True, "typical_response_hours": 24},
                  rules=[{"field": "customer_type", "op": "in", "value": ["SALARIED", "SME"], "label": "Earning customer"},
                         {"field": "purpose_category", "op": "in", "value": ["school_fees"], "label": "School fees"}])
    pb = _product(db, biz, ad, name="Small Business Boost", family="SME_WORKING_CAPITAL",
                  terms={"min_amount": 1_000_000, "max_amount": 40_000_000, "min_tenor_months": 3,
                         "max_tenor_months": 18, "pricing_display": "2% per month (indicative)",
                         "collateral_required": False, "digital_journey": True, "typical_response_hours": 24},
                  rules=[{"field": "customer_type", "op": "in", "value": ["SME"], "label": "Business owner"},
                         {"field": "business_age_months", "op": "gte", "value": 6, "label": "Operating 6+ months"}])
    _appetite(db, biz, ad, name="Members & Salaried Workers", product_ids=[str(ps), str(pf)], min_match_score=60,
              criteria=[{"field": "employment_type", "op": "in", "value": ["permanent", "contract"], "weight": 2,
                         "label": "Permanent or contract staff"},
                        {"field": "region", "op": "in", "value": ["Central", "Eastern"], "weight": 1,
                         "label": "Central & Eastern"}], capacity_limits={"daily_count": 30})
    _appetite(db, biz, ad, name="Micro-SME Working Capital", product_ids=[str(pb), str(pf)], min_match_score=60,
              criteria=[{"field": "monthly_turnover", "op": "gte", "value": 1_000_000, "weight": 1,
                         "label": "Turnover UGX 1M+"},
                        {"field": "amount", "op": "lte", "value": 25_000_000, "weight": 1, "label": "Tickets up to UGX 25M"}],
              capacity_limits={"daily_count": 20}, target_count=150)
    inst_svc.save_routing(db, ad, inst.id, [{"name": "All requests → Member Loans", "conditions": {},
                                             "target_team_id": str(t1.id)}], None)
    inst_svc.save_notification_prefs(db, ad, inst.id, inst_svc.default_notification_prefs())
    inst_svc.activate(db, ad, inst)
    result["pearl"] = {"inst": inst, "users": {**people, "admin": admin}}

    # ---------------- Kijani Microfinance
    inst, admin = make("Kijani Microfinance Uganda Ltd", "Kijani Microfinance", "Microfinance Deposit-taking Institution",
                       "BOU/MDI/0007-DEMO", "Bank of Uganda", "kijani.demo",
                       "Agricultural and clean-energy finance across Northern, Eastern and Western Uganda.",
                       ["Northern", "Eastern", "Western"])
    inst_svc.verify(db, ops, inst, True, "Licence verified (demo)")
    t1, t2 = Team(institution_id=inst.id, name="Agribusiness North"), Team(institution_id=inst.id, name="Agribusiness South")
    db.add_all([t1, t2])
    db.flush()
    people = _staff(db, inst, "kijani.demo", [
        ("credit", "Okot Jimmy", ["CREDIT_RISK", "BUSINESS"], None), ("manager", "Lydia Apio", ["MANAGER"], None),
        ("officer", "Simon Ojok", ["OFFICER"], "Agribusiness North"),
        ("officer2", "Mercy Atuhaire", ["OFFICER"], "Agribusiness South")],
        {"Agribusiness North": t1.id, "Agribusiness South": t2.id})
    cr, ad = _actor(db, people["credit"]), _actor(db, admin)
    pa = _product(db, cr, ad, name="Agri Inputs Loan", family="AGRI_INPUTS",
                  terms={"min_amount": 300_000, "max_amount": 15_000_000, "min_tenor_months": 3, "max_tenor_months": 12,
                         "pricing_display": "Seasonal repayment (indicative 22% p.a.)", "collateral_required": False,
                         "digital_journey": True, "typical_response_hours": 48},
                  rules=[{"field": "customer_type", "op": "in", "value": ["AGRICULTURE"], "label": "Farmer"},
                         {"field": "operating_months", "op": "gte", "value": 12, "label": "Farming for 1+ year"}])
    pg = _product(db, cr, ad, name="Agri Asset Finance", family="AGRI_ASSET",
                  terms={"min_amount": 2_000_000, "max_amount": 60_000_000, "min_tenor_months": 6, "max_tenor_months": 36,
                         "pricing_display": "From 20% p.a. (indicative)", "collateral_required": True,
                         "digital_journey": False, "typical_response_hours": 72},
                  rules=[{"field": "customer_type", "op": "in", "value": ["AGRICULTURE"], "label": "Farmer"},
                         {"field": "annual_income", "op": "gte", "value": 5_000_000, "label": "Farm income UGX 5M+ a year"}])
    pso = _product(db, cr, ad, name="Solar for Home & Business", family="ASSET_FINANCE",
                   terms={"min_amount": 500_000, "max_amount": 8_000_000, "min_tenor_months": 6, "max_tenor_months": 24,
                          "pricing_display": "Pay-as-you-go (indicative)", "collateral_required": False,
                          "digital_journey": True, "typical_response_hours": 24},
                   rules=[{"field": "purpose_category", "op": "in", "value": ["solar", "equipment"],
                           "label": "Solar / energy equipment"}])
    _appetite(db, cr, ad, name="Northern & Eastern Agriculture", product_ids=[str(pa), str(pg)], min_match_score=60,
              criteria=[{"field": "region", "op": "in", "value": ["Northern", "Eastern", "Western"], "weight": 2,
                         "label": "Northern, Eastern & Western regions"},
                        {"field": "farm_activity", "op": "in", "value": ["crops", "dairy", "poultry", "mixed"],
                         "weight": 1, "label": "Crops, dairy, poultry or mixed"}], capacity_limits={"daily_count": 25})
    _appetite(db, cr, ad, name="Clean Energy", product_ids=[str(pso)], min_match_score=55, criteria=[])
    inst_svc.save_routing(db, ad, inst.id, [
        {"name": "Northern region → Agribusiness North", "conditions": {"regions": ["Northern"]},
         "target_team_id": str(t1.id)},
        {"name": "Other agriculture → Agribusiness South", "conditions": {"customer_types": ["AGRICULTURE"]},
         "target_team_id": str(t2.id)}], None)  # solar for non-farmers deliberately falls to the Unassigned queue
    inst_svc.save_notification_prefs(db, ad, inst.id, inst_svc.default_notification_prefs())
    inst_svc.activate(db, ad, inst)
    result["kijani"] = {"inst": inst, "users": {**people, "admin": admin}}

    # ---------------- Nile Fintech — awaiting WEZA verification (demo of onboarding)
    inst, admin = make("Nile Digital Credit Ltd", "Nile Fintech", "Fintech Lender", "UMRA/T4/2219-DEMO",
                       "Uganda Microfinance Regulatory Authority", "nile.demo", "Digital nano-loans.", ["Central"])
    result["nile"] = {"inst": inst, "users": {"admin": admin}}
    for key in ("lakeside", "pearl", "kijani"):
        c = db.execute(select(Contract).where(Contract.institution_id == result[key]["inst"].id)).scalar_one()
        c.included_opportunities = {"lakeside": 25, "pearl": 15, "kijani": 15}[key]
        c.opportunity_price = Decimal({"lakeside": 75_000, "pearl": 25_000, "kijani": 30_000}[key])
        c.subscription_fee = Decimal({"lakeside": 2_500_000, "pearl": 750_000, "kijani": 1_000_000}[key])
    return result


def seed_demo_bank(db: Session) -> dict:
    """Demo Bank — the institution the end-to-end demonstration runs through (Goal 1).

    One active SME Working Capital product, one active appetite carrying a full mandate, and one
    user for each canonical role (plus the product lead the maker-checker rule needs), so the
    demonstration exercises role isolation for real rather than in theory.

    Unlike the other demo institutions, Demo Bank's people hold the canonical role names
    (INSTITUTION_ADMIN, INSTITUTION_MANAGER, INSTITUTION_OFFICER, COMPLIANCE_VIEWER) — which is
    what makes it the demonstration of the Goal 1 role vocabulary.
    """
    from weza.domains.identity.models import Membership
    from weza.domains.trust import roles as canon

    ops = Actor(kind="WEZA_USER", roles=frozenset({"WEZA_OPS"}), display="Tendo Operations (seed)")
    inst, admin = inst_svc.apply(db, {
        "legal_name": "Demo Bank Limited", "display_name": "Demo Bank", "institution_type": "Commercial Bank",
        "licence_no": "BOU/CB/0000-DEMO", "regulator": "Bank of Uganda",
        "description": "Demo institution for the WEZA V1 end-to-end demonstration.",
        "accept_terms": True,
        "representative": {"name": "Demo Bank Representative", "email": "rep@demobank.demo",
                           "phone": "+256700000001", "title": "Head of SME"},
        "compliance": {"name": "Demo Bank Compliance", "email": "compliance@demobank.demo"},
        "admin_name": "Demo Bank Administrator", "admin_email": "admin@demobank.demo",
        "admin_password": DEMO_PASSWORD})
    inst.profile = {**inst.profile, "regions_served": ["Central", "Western"]}
    inst_svc.verify(db, ops, inst, True, "Licence and representative verified (demo)")
    # The administrator created at application time takes the canonical administrator role.
    db.execute(select(Membership).where(Membership.user_id == admin.id)).scalar_one().roles = \
        [canon.INSTITUTION_ADMIN]
    team = Team(institution_id=inst.id, name="SME Desk")
    db.add(team)
    db.flush()
    people = _staff(db, inst, "demobank.demo", [
        ("manager", "Erasmus Byaruhanga", [canon.INSTITUTION_MANAGER], "SME Desk"),
        ("officer", "Sarah Namazzi", [canon.INSTITUTION_OFFICER], "SME Desk"),
        ("compliance", "Geoffrey Ssekandi", [canon.COMPLIANCE_VIEWER], None),
        # The product lead drafts; the administrator approves (maker-checker: two different people).
        ("business", "Miriam Auma", ["BUSINESS"], None),
    ], {"SME Desk": team.id})
    biz, ad = _actor(db, people["business"]), _actor(db, admin)
    p1 = _product(db, biz, ad, name="SME Working Capital", family="SME_WORKING_CAPITAL",
                  terms={"min_amount": 1_000_000, "max_amount": 50_000_000, "min_tenor_months": 3,
                         "max_tenor_months": 24, "pricing_display": "From 20% p.a. (indicative)",
                         "collateral_required": False, "digital_journey": True, "typical_response_hours": 24,
                         "description": "Working capital for established small and medium businesses."},
                  rules=[{"field": "customer_type", "op": "in", "value": ["SME"], "label": "Business owner"},
                         {"field": "business_age_months", "op": "gte", "value": 6,
                          "label": "Operating for at least 6 months"}],
                  requirements=[{"doc_type": "business_registration", "label": "Business registration certificate",
                                 "required": False},
                                {"doc_type": "bank_statement", "label": "6-month bank statement", "required": False}])
    _appetite(db, biz, ad, name="SME Working Capital Mandate", product_ids=[str(p1)], min_match_score=60,
              criteria=[{"field": "monthly_turnover", "op": "gte", "value": 1_000_000, "weight": 1,
                         "label": "Turnover UGX 1M+ a month"}],
              # The mandate, as first-class dimensions (Goal 1 §4).
              customer_types=["SME"],
              sectors=["retail_trade", "wholesale_trade", "manufacturing", "services", "agriculture"],
              regions=["Central", "Western"], min_amount=1_000_000, max_amount=50_000_000,
              min_business_age_months=6,
              target_count=100, target_value=3_000_000_000, capacity_limits={"daily_count": 40},
              campaign_from=str(date.today() - timedelta(days=30)), campaign_to=str(date.today() + timedelta(days=90)))
    inst_svc.save_routing(db, ad, inst.id, [
        {"name": "All SME requests → SME Desk", "conditions": {"customer_types": ["SME"]},
         "target_team_id": str(team.id)}],
        {"ack_within_minutes": 120, "first_contact_within_minutes": 480, "escalate_after_minutes": 1440})
    inst_svc.save_notification_prefs(db, ad, inst.id, inst_svc.default_notification_prefs())
    inst_svc.activate(db, ad, inst)
    return {"inst": inst, "users": {**people, "admin": admin}}


def _demo_need(rng: random.Random, i: int) -> dict:
    kind = rng.choices(["SME", "SALARIED", "AGRICULTURE", "SOLAR", "HUGE"], [0.5, 0.22, 0.18, 0.06, 0.04])[0]
    from weza.domains.admin_config import UGANDA
    regions = UGANDA["regions"]
    if kind == "AGRICULTURE":
        district = rng.choice(regions["Northern"] + regions["Eastern"] + regions["Western"][:3])
    else:
        district = rng.choice(regions["Central"] * 3 + regions["Western"] + regions["Eastern"] + regions["Northern"][:2])
    if kind == "SME" or kind == "HUGE":
        sector = rng.choice(["health_pharmacy", "retail_trade", "manufacturing", "wholesale_trade", "hospitality",
                             "beauty", "transport", "construction", "education"])
        purpose = rng.choice(["expansion", "stock", "working_capital", "equipment"])
        amount = rng.choice([2, 3, 5, 8, 10, 15, 20, 30, 40, 60, 75, 120]) * 1_000_000 if kind == "SME" else \
            rng.choice([800, 1500, 2500]) * 1_000_000
        facts = {"business.name": f"{rng.choice(LAST)} {rng.choice(['Enterprises', 'Traders', 'Pharmacy', 'Stores', 'Works'])}",
                 "business.sector": sector, "business.district": district,
                 "business.age_months": rng.choice([5, 9, 14, 20, 30, 48, 84]),
                 "business.monthly_turnover": rng.choice([1.5, 2.5, 4, 6, 9, 14, 25, 40]) * 1_000_000,
                 "business.registered": rng.random() > 0.25,
                 "finance.monthly_repayments": rng.choice([0, 0, 0, 300_000, 800_000, 2_000_000]),
                 "need.tenor_months": rng.choice([6, 12, 18, 24, 36])}
        return {"customer_type": "SME", "sector": sector, "purpose_category": purpose, "amount": amount,
                "purpose": {"expansion": "Expand the business", "stock": "Buy stock", "working_capital": "Working capital",
                            "equipment": "Buy equipment"}[purpose], "district": district, "facts": facts}
    if kind == "SALARIED":
        purpose = rng.choice(["school_fees", "school_fees", "home_improvement", "personal", "medical"])
        facts = {"employment.employer": rng.choice(["Ministry of Education", "Kampala Capital City Authority",
                                                    "Mulago Hospital", "Private school", "NGO"]),
                 "employment.type": rng.choice(["permanent", "permanent", "contract", "casual"]),
                 "employment.months": rng.choice([4, 10, 18, 36, 72]),
                 "employment.monthly_net_income": rng.choice([0.5, 0.9, 1.4, 2.2, 3.5]) * 1_000_000,
                 "residence.district": district, "finance.monthly_repayments": rng.choice([0, 0, 150_000, 400_000]),
                 "need.tenor_months": rng.choice([3, 6, 12])}
        return {"customer_type": "SALARIED", "sector": None, "purpose_category": purpose,
                "amount": rng.choice([0.8, 1.5, 2, 3, 5, 8]) * 1_000_000,
                "purpose": {"school_fees": "School fees", "home_improvement": "Home improvement", "personal": "Personal",
                            "medical": "Medical bills"}[purpose], "district": district, "facts": facts}
    if kind == "SOLAR":
        facts = {"employment.employer": "Self", "employment.type": "casual", "employment.months": 24,
                 "employment.monthly_net_income": 900_000, "residence.district": district,
                 "finance.monthly_repayments": 0}
        return {"customer_type": "SALARIED", "sector": None, "purpose_category": "solar",
                "amount": rng.choice([1.2, 2.5, 4]) * 1_000_000, "purpose": "Solar system for my home",
                "district": district, "facts": facts}
    facts = {"farm.activity": rng.choice(["crops", "dairy", "poultry", "mixed", "fish"]), "farm.district": district,
             "farm.operating_months": rng.choice([8, 18, 36, 72]),
             "farm.annual_income": rng.choice([2, 4, 7, 12, 25]) * 1_000_000,
             "finance.monthly_repayments": rng.choice([0, 0, 100_000])}
    purpose = rng.choice(["agri_inputs", "agri_inputs", "equipment", "expansion"])
    return {"customer_type": "AGRICULTURE", "sector": "agriculture", "purpose_category": purpose,
            "amount": rng.choice([0.6, 1.5, 3, 5, 9, 20]) * 1_000_000,
            "purpose": {"agri_inputs": "Seeds and fertiliser", "equipment": "Farm equipment",
                        "expansion": "Expand the farm"}[purpose], "district": district, "facts": facts}


def seed_demo_customers(db: Session, inst_map: dict, n: int = 150) -> None:
    rng = random.Random(2026)
    now = utcnow()
    users_by_inst = {v["inst"].id: v["users"] for v in inst_map.values()}
    created = []
    for i in range(n):
        spec = _demo_need(rng, i)
        phone = f"+2567009{i:05d}"
        cust, _ = customer_svc.get_or_create_by_phone(db, phone, is_demo=True)
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        customer_svc.upsert_fact(db, cust.id, "identity.full_name", name, confirmed=True)
        if rng.random() > 0.35:
            customer_svc.upsert_fact(db, cust.id, "identity.nin",
                                     f"C{'MF'[i % 2]}{rng.randint(10**9, 10**10 - 1)}{'ABCD'[i % 4]}{'WXYZ'[i % 4]}",
                                     confirmed=True)
        cust.customer_type = spec["customer_type"]
        for k, v in spec["facts"].items():
            customer_svc.upsert_fact(db, cust.id, k, v, source="CUSTOMER", channel=rng.choice(["web", "whatsapp"]),
                                     confirmed=True)
        age = timedelta(days=rng.randint(0, 40), hours=rng.randint(0, 23))
        need = FinancialNeed(customer_id=cust.id, amount=Decimal(str(spec["amount"])), purpose=spec["purpose"],
                             purpose_category=spec["purpose_category"], customer_type=spec["customer_type"],
                             sector=spec["sector"], district=spec["district"], region=region_of(spec["district"]),
                             status="READY_FOR_MATCHING", intent_confirmed_at=now - age, is_demo=True,
                             tenor_months=spec["facts"].get("need.tenor_months"))
        db.add(need)
        db.flush()
        res = engine.match_need(db, need, trigger="seed")
        created.append((need, cust, res, age))
    db.flush()

    # Convert a share of READY needs into opportunities through the real saga.
    reasons = ["INCOME_TURNOVER"] * 6 + ["AFFORDABILITY", "DOCUMENTATION", "COLLATERAL", "UNREACHABLE"]
    for idx, (need, cust, res, age) in enumerate(created):
        if res["readiness"] == "NO_CURRENT_MATCH":
            if idx % 2 == 0:
                engine.opt_in_waiting(db, need)
            continue
        if res["readiness"] != "READY_NOW" or idx % 10 in (3, 7):
            continue  # leave some matched-but-not-submitted demand in the market
        ready = res["ready"]
        lake = [m for m in ready if m.institution_id == inst_map["lakeside"]["inst"].id]
        m = lake[0] if lake and idx % 5 != 0 else ready[0]
        tpl = consent_svc.current_template(db)
        actor = Actor(kind="CUSTOMER", id=cust.id, display="customer")
        c = consent_svc.grant(db, actor, customer_id=cust.id, institution_id=m.institution_id, need_id=need.id,
                              match_id=m.id, template_id=tpl.id)
        need.status = "CONSENTED"
        try:
            with db.begin_nested():
                opp = opp_svc.qualify(db, actor, need, m, c)
        except opp_svc.RematchRequired:
            need.status = "READY_FOR_MATCHING"
            engine.match_need(db, need, trigger="seed_capacity")  # e.g. mandate reached daily capacity
            continue
        a = opp_svc.assign_by_rules(db, opp)
        back = age
        opp.qualified_at = now - back
        opp.routed_at = now - back + timedelta(minutes=1)
        opp.last_activity_at = now - back
        if a.first_contact_due_at:
            a.first_contact_due_at = opp.routed_at + (a.first_contact_due_at - (opp.routed_at or now))
        if a.assigned_at:
            a.assigned_at = opp.routed_at
        _progress(db, opp, a, users_by_inst[opp.institution_id], rng, idx, reasons, back,
                  lake=opp.institution_id == inst_map["lakeside"]["inst"].id)
        if opp.state in opp_svc.OPEN_STATES - {"REPORTED_APPROVED"}:
            # Keep in-flight demo work recent so the demo opens on a live queue, not an expired one.
            recent = timedelta(hours=rng.randint(2, 30))
            opp.qualified_at, opp.routed_at = now - recent, now - recent + timedelta(minutes=1)
            opp.last_activity_at = now - recent / 2
            if a.first_contact_due_at:
                st_minutes = 480 if opp.institution_id == inst_map["lakeside"]["inst"].id else 1440
                a.first_contact_due_at = opp.routed_at + timedelta(minutes=st_minutes)
            if a.assigned_at:
                a.assigned_at = opp.routed_at
            if a.first_contact_at:
                a.first_contact_at = opp.routed_at + timedelta(hours=1)
    db.flush()
    # Backdate demand so trend charts and freshness look like a live market.
    for need, _, _, age in created:
        db.execute(update(FinancialNeed).where(FinancialNeed.id == need.id).values(created_at=now - age))


def _progress(db, opp, a, users, rng, idx, reasons, back, lake=False):
    """Move demo opportunities through realistic, institution-reported states."""
    owner = a.user_id
    officer_user = next((u for u in users.values() if u.id == owner), None) or users.get("manager") or users["admin"]
    actor = identity.actor_for_user(db, officer_user, True)
    if "OFFICER" not in actor.roles and "MANAGER" not in actor.roles:
        return
    stage = rng.random()
    t_fresh, t_contacted, t_proceeding = (0.06, 0.12, 0.18) if lake else (0.25, 0.4, 0.55)
    if back < timedelta(hours=10) or stage < t_fresh:
        return  # fresh: still awaiting first contact
    if a.user_id is None:
        return
    opp_svc.update_status(db, actor, opp, "CONTACTED", "Called the customer (demo)")
    a.first_contact_at = opp.routed_at + timedelta(hours=rng.choice([1, 2, 3, 5, 9, 20]))
    if stage < t_contacted:
        return
    opp_svc.update_status(db, actor, opp, "PROCEEDING", "Customer moving into our internal process (demo)")
    if stage < t_proceeding:
        return
    opp_svc.update_status(db, actor, opp, "SUBMITTED_TO_INSTITUTION", "Application lodged internally (demo)")
    if stage < (0.9 if lake else 0.7):
        # Lakeside's demo declines skew to turnover, so the Outcome Learning Loop raises an appetite insight.
        reason = "INCOME_TURNOVER" if lake and idx % 5 else reasons[idx % len(reasons)]
        opp_svc.report_outcome(db, actor, opp, state="REPORTED_DECLINED", reason_category=reason,
                               reason_note="Reported by institution (demo)")
        return
    opp_svc.report_outcome(db, actor, opp, state="REPORTED_APPROVED", approved_amount=opp.amount)
    if stage > 0.82:
        opp_svc.report_outcome(db, actor, opp, state="REPORTED_DISBURSED",
                               disbursed_amount=(opp.amount * Decimal("0.9")).quantize(Decimal("1")),
                               disbursed_on=date.today() - timedelta(days=max(0, back.days - 2)))


def seed(force: bool = False) -> bool:
    s = get_settings()
    if s.is_production:
        raise RuntimeError("Demo seed never runs in production.")
    with session_scope() as db:
        if db.execute(select(func.count()).select_from(Institution)).scalar_one() and not force:
            return False
        seed_config(db)
        seed_weza_staff(db)
        inst_map = seed_institutions(db)
        inst_map["demobank"] = seed_demo_bank(db)
    drain()
    with session_scope() as db:
        inst_map = {k: {"inst": db.get(Institution, v["inst"].id),
                        "users": {uk: db.get(User, u.id) for uk, u in v["users"].items()}} for k, v in
                    _reload(db).items()}
        seed_demo_customers(db, inst_map)
    drain()
    with session_scope() as db:
        insights.outcome_insights_job(db)
        _backfill_activity(db)
    drain()
    return True


def _reload(db: Session) -> dict:
    out = {}
    for key, domain in (("lakeside", "lakeside.demo"), ("pearl", "pearl.demo"), ("kijani", "kijani.demo"),
                        ("demobank", "demobank.demo")):
        users = {u.email.split("@")[0]: u for u in db.execute(select(User).where(User.email.like(f"%@{domain}"))).scalars()}
        from weza.domains.identity.models import Membership
        m = db.execute(select(Membership).where(Membership.user_id == users["admin"].id)).scalar_one()
        out[key] = {"inst": db.get(Institution, m.institution_id), "users": users}
    return out


def _backfill_activity(db: Session) -> None:
    """Align activity timestamps with backdated opportunities so timelines read naturally."""
    for opp in db.execute(select(Opportunity).where(Opportunity.is_demo.is_(True))).scalars():
        acts = db.execute(select(Activity).where(Activity.opportunity_id == opp.id).order_by(Activity.at)).scalars().all()
        t = opp.qualified_at
        for i, a in enumerate(acts):
            a.at = t + timedelta(hours=i * 7)
        if acts:
            opp.last_activity_at = acts[-1].at
        for out in db.execute(select(Outcome).where(Outcome.opportunity_id == opp.id)).scalars():
            out.reported_at = opp.last_activity_at
        a = db.get(Assignment, opp.id)
        if a and a.first_contact_at and a.first_contact_at < opp.routed_at:
            a.first_contact_at = opp.routed_at + timedelta(hours=2)


if __name__ == "__main__":
    from weza.platform.logging import configure_logging
    configure_logging("WARNING")
    print("seeded" if seed() else "already seeded")
