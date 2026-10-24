"""WEZA V1 foundation (Goal 1).

The four things a real end-to-end demonstration rests on:

* the canonical role vocabulary and the tenant isolation it must not weaken;
* institution ownership — a product and an appetite belong to exactly one institution;
* consent — customer data reaches an institution only through an explicit, institution-bound,
  auditable consent;
* the mandate and the journey — what an institution will lend to, and what WEZA knows about the
  customer's phone.

Everything here is asserted against the seeded Demo Bank, whose people hold the canonical role names.
"""

import uuid

import pytest
from sqlalchemy import select

from tests.helpers import idem, opp_for
from weza.domains.appetite.mandate import mandate_rules
from weza.domains.consent.models import Consent
from weza.domains.identity.models import Membership
from weza.domains.institution.models import Institution
from weza.domains.matching import engine
from weza.domains.opportunity.models import Opportunity
from weza.domains.product.models import Product
from weza.domains.trust import policy
from weza.domains.trust import roles as canon
from weza.platform.context import Actor
from weza.platform.db import session_scope, utcnow

DEMO_BANK = "Demo Bank"


def _actor(*roles: str) -> Actor:
    return Actor(kind="INSTITUTION_USER", roles=canon.expand(roles))


# ------------------------------------------------------------------ 2. users and roles


def test_canonical_and_working_roles_name_the_same_role():
    """Whichever spelling an institution grants, the actor holds both — so no existing check changes."""
    assert canon.expand(["OFFICER"]) == frozenset({"OFFICER", "INSTITUTION_OFFICER"})
    assert canon.expand(["INSTITUTION_OFFICER"]) == frozenset({"OFFICER", "INSTITUTION_OFFICER"})
    assert canon.expand(["MANAGER"]) == frozenset({"MANAGER", "INSTITUTION_MANAGER"})
    assert canon.expand(["INSTITUTION_MANAGER"]) == frozenset({"MANAGER", "INSTITUTION_MANAGER"})
    assert canon.expand(["INST_ADMIN"]) == frozenset({"INST_ADMIN", "INSTITUTION_ADMIN"})
    assert canon.expand(["INSTITUTION_ADMIN"]) == frozenset({"INST_ADMIN", "INSTITUTION_ADMIN"})
    assert canon.expand(["COMPLIANCE_VIEWER"]) == frozenset({"COMPLIANCE", "COMPLIANCE_VIEWER"})
    assert canon.expand(["WEZA_SUPER"]) == frozenset({"WEZA_ADMIN", "WEZA_SUPER"})
    # Working roles with no canonical equivalent keep their own meaning.
    assert canon.expand(["BUSINESS"]) == frozenset({"BUSINESS"})


def test_canonical_roles_carry_their_working_permissions():
    assert policy.has(_actor("INSTITUTION_ADMIN"), "users.manage")
    assert policy.has(_actor("INSTITUTION_MANAGER"), "opportunity.assign")
    assert policy.has(_actor("INSTITUTION_OFFICER"), "opportunity.update_status")
    assert policy.has(_actor("COMPLIANCE_VIEWER"), "consent.audit")
    # ...and no more than the working role they stand for.
    assert not policy.has(_actor("INSTITUTION_OFFICER"), "users.manage")
    assert not policy.has(_actor("INSTITUTION_OFFICER"), "opportunity.assign")
    assert not policy.has(_actor("COMPLIANCE_VIEWER"), "opportunity.update_status")


def test_demo_bank_people_hold_the_canonical_roles(client, as_user):
    """The seeded Demo Bank staff hold the canonical names, and the API accepts them."""
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == DEMO_BANK)).scalar_one()
        roles = {m.user_id: m.roles for m in db.execute(
            select(Membership).where(Membership.institution_id == inst.id)).scalars()}
    held = {r for rs in roles.values() for r in rs}
    assert canon.INSTITUTION_ADMIN in held
    assert canon.INSTITUTION_MANAGER in held
    assert canon.INSTITUTION_OFFICER in held
    assert canon.COMPLIANCE_VIEWER in held


def test_a_canonical_role_can_be_granted_and_used(client, as_user):
    """An administrator grants INSTITUTION_OFFICER; that person then works as an officer."""
    admin = as_user("admin@demobank.demo")
    email = f"new-officer-{uuid.uuid4().hex[:8]}@demobank.demo"
    r = client.post("/api/v1/inst/users", json={"email": email, "full_name": "New Officer",
                                               "password": "WezaDemo!2026", "roles": [canon.INSTITUTION_OFFICER]},
                    headers=admin)
    assert r.status_code == 201, r.text
    h = as_user(email)
    ws = client.get("/api/v1/inst/workspace", headers=h).json()
    assert "opportunity.update_status" in ws["permissions"]
    assert "users.manage" not in ws["permissions"]
    assert ws["institution"]["display_name"] == DEMO_BANK


def test_an_unknown_role_is_refused(client, as_user):
    admin = as_user("admin@demobank.demo")
    r = client.post("/api/v1/inst/users", json={"email": f"typo-{uuid.uuid4().hex[:8]}@demobank.demo",
                                               "full_name": "Typo Role", "password": "WezaDemo!2026",
                                               "roles": ["INSTITUTION_MANGER"]}, headers=admin)
    assert r.status_code in (400, 422), r.text


# ------------------------------------------------------------------ 1. institutions


def test_institution_reports_the_canonical_status_and_its_primary_contact(client, as_user):
    h = as_user("admin@demobank.demo")
    inst = client.get("/api/v1/inst/workspace", headers=h).json()["institution"]
    assert inst["canonical_status"] == "active"
    assert inst["status"] == "ACTIVE"
    assert inst["activation"]["activated_at"]
    assert inst["primary_contact"]["email"] == "rep@demobank.demo"
    assert inst["primary_contact"]["is_primary"] is True


def test_a_new_application_is_pending_review(client):
    r = client.post("/api/v1/institutions/applications", json={
        "legal_name": "Prospect Bank Limited", "display_name": "Prospect Bank", "institution_type": "Commercial Bank",
        "licence_no": "BOU/CB/9999-DEMO", "regulator": "Bank of Uganda", "description": "Applying to join.",
        "website": "", "representative": {"name": "Rep Person", "email": "rep@prospect.demo", "phone": "",
                                          "title": ""},
        "compliance": {"name": "Comp Person", "email": "comp@prospect.demo", "phone": "", "title": ""},
        "admin_name": "Prospect Admin", "admin_email": f"admin-{uuid.uuid4().hex[:8]}@prospect.demo",
        "admin_password": "WezaDemo!2026", "accept_terms": True})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "SUBMITTED"
    with session_scope() as db:
        inst = db.get(Institution, uuid.UUID(r.json()["institution_id"]))
        assert inst.canonical_status == "pending_review"
        contact = db.execute(select(Institution).where(Institution.id == inst.id)).scalar_one()
        assert contact.status == "SUBMITTED"


def test_only_one_primary_contact_per_institution(client, as_user):
    """The database refuses a second primary contact for the same institution."""
    from sqlalchemy.exc import IntegrityError

    h = as_user("admin@demobank.demo")
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == DEMO_BANK)).scalar_one()
        from weza.domains.institution.models import Contact
        db.add(Contact(institution_id=inst.id, kind="BUSINESS", name="Second Primary", email="second@demobank.demo",
                       is_primary=True))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
        else:
            db.rollback()
            pytest.fail("a second primary contact was accepted")
    contacts = client.get("/api/v1/inst/contacts", headers=h).json()
    assert sum(1 for c in contacts["contacts"] if c["is_primary"]) == 1


def test_a_canonically_named_officer_still_appears_in_the_team(client, as_user):
    """The staff surface must not depend on which spelling the institution granted."""
    email = f"canon-officer-{uuid.uuid4().hex[:8]}@demobank.demo"
    admin = as_user("admin@demobank.demo")
    r = client.post("/api/v1/inst/users", json={"email": email, "full_name": "Canonical Officer",
                                               "password": "WezaDemo!2026",
                                               "roles": [canon.INSTITUTION_OFFICER]}, headers=admin)
    assert r.status_code == 201, r.text
    team = client.get("/api/v1/inst/team", headers=as_user("manager@demobank.demo"))
    assert team.status_code == 200, team.text
    members = team.json()["members"]
    me = next(m for m in members if m["email"] == email)
    # The team page shows the roles as granted, and the expanded set carries both spellings.
    assert me["roles"] == [canon.INSTITUTION_OFFICER]
    assert "OFFICER" in me["role_set"] and canon.INSTITUTION_OFFICER in me["role_set"]


# ------------------------------------------------------------------ 3 & 4. institution ownership


def test_a_product_belongs_to_exactly_one_institution(client, as_user):
    """A product row is owned by the institution that created it, and only that institution can use it."""
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == DEMO_BANK)).scalar_one()
        other = db.execute(select(Institution).where(Institution.display_name == "Lakeside Bank")).scalar_one()
        demo_product = db.execute(select(Product).where(Product.institution_id == inst.id)).scalars().first()
        foreign_product = db.execute(select(Product).where(Product.institution_id == other.id)).scalars().first()
        assert demo_product.institution_id == inst.id != foreign_product.institution_id
        demo_product_id, foreign_product_id = str(demo_product.id), str(foreign_product.id)
    h = as_user("business@demobank.demo")
    r = client.post("/api/v1/inst/appetites", json={"name": "Borrowed product", "product_ids": [foreign_product_id]},
                    headers=h)
    assert r.status_code in (400, 422), r.text
    assert "product" in r.text.lower()
    # The institution's own product is accepted.
    r = client.post("/api/v1/inst/appetites", json={"name": "Own product", "product_ids": [demo_product_id]},
                    headers=h)
    assert r.status_code == 201, r.text


def test_an_appetite_of_another_institution_is_not_found(client, as_user):
    with session_scope() as db:
        other = db.execute(select(Institution).where(Institution.display_name == "Lakeside Bank")).scalar_one()
        from weza.domains.appetite.models import Appetite
        ap = db.execute(select(Appetite).where(Appetite.institution_id == other.id)).scalars().first()
        appetite_id = str(ap.id)
    h = as_user("admin@demobank.demo")
    assert client.get(f"/api/v1/inst/appetites/{appetite_id}", headers=h).status_code == 404


def test_another_tenants_opportunity_is_not_found(client, as_user):
    """Isolation: Demo Bank staff cannot see or touch a Lakeside record, and the other way round."""
    lakeside_opp, _ = opp_for("Lakeside Bank")
    h = as_user("manager@demobank.demo")
    assert client.get(f"/api/v1/inst/opportunities/{lakeside_opp}", headers=h).status_code == 404
    assert client.get("/api/v1/inst/opportunities", headers=h).json()["items"] is not None
    demo_opp, _ = opp_for(DEMO_BANK)
    lh = as_user("manager@lakeside.demo")
    assert client.get(f"/api/v1/inst/opportunities/{demo_opp}", headers=lh).status_code == 404


def test_an_officer_sees_only_their_own_work(client, as_user):
    """Role isolation: an officer holds no institution-wide read of other people's opportunities."""
    demo_opp, owner = opp_for(DEMO_BANK)
    h = as_user("officer@demobank.demo")
    assert client.get(f"/api/v1/inst/opportunities/{demo_opp}", headers=h).status_code in (200, 404)
    admin = as_user("admin@demobank.demo")
    r = client.get(f"/api/v1/inst/opportunities/{demo_opp}", headers=admin)
    assert r.status_code == 200, r.text
    # A second officer (created here) must not see the first officer's work.
    email = f"officer2-{uuid.uuid4().hex[:8]}@demobank.demo"
    client.post("/api/v1/inst/users", json={"email": email, "full_name": "Second Officer",
                                            "password": "WezaDemo!2026",
                                            "roles": [canon.INSTITUTION_OFFICER]}, headers=admin)
    h2 = as_user(email)
    assert client.get(f"/api/v1/inst/opportunities/{demo_opp}", headers=h2).status_code == 404


# ------------------------------------------------------------------ 4. the mandate


def test_the_mandate_is_stored_and_returned(client, as_user):
    """The six mandate dimensions are first class, not buried in the criteria blob."""
    h = as_user("business@demobank.demo")
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == DEMO_BANK)).scalar_one()
        product = db.execute(select(Product).where(Product.institution_id == inst.id)).scalars().first()
        product_id = str(product.id)
    body = {"name": "Retail Only Mandate", "product_ids": [product_id], "min_match_score": 60,
            "criteria": [{"field": "monthly_turnover", "op": "gte", "value": 1_000_000, "weight": 1}],
            "customer_types": ["SME"], "sectors": ["retail_trade"], "regions": ["Central"],
            "min_amount": 1_000_000, "max_amount": 20_000_000, "min_business_age_months": 6}
    r = client.post("/api/v1/inst/appetites", json=body, headers=h)
    assert r.status_code == 201, r.text
    mandate = r.json()["version"]["mandate"]
    assert mandate["customer_types"] == ["SME"]
    assert mandate["sectors"] == ["retail_trade"]
    assert mandate["regions"] == ["Central"]
    assert mandate["min_amount"] == 1_000_000
    assert mandate["max_amount"] == 20_000_000
    assert mandate["min_business_age_months"] == 6
    assert mandate["activation_state"] == "DRAFT"
    listed = client.get("/api/v1/inst/appetites", headers=h).json()["appetites"]
    assert any(a["mandate"]["sectors"] == ["retail_trade"] for a in listed)


def test_a_mandate_value_outside_the_vocabulary_is_refused(client, as_user):
    h = as_user("business@demobank.demo")
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == DEMO_BANK)).scalar_one()
        product = db.execute(select(Product).where(Product.institution_id == inst.id)).scalars().first()
        product_id = str(product.id)
    r = client.post("/api/v1/inst/appetites", json={"name": "Bad sector", "product_ids": [product_id],
                                                    "sectors": ["time_travel"]}, headers=h)
    assert r.status_code in (400, 422), r.text
    r = client.post("/api/v1/inst/appetites", json={"name": "Bad customer type", "product_ids": [product_id],
                                                    "customer_types": ["ROBOT"]}, headers=h)
    assert r.status_code in (400, 422), r.text


def test_the_mandate_excludes_a_customer_outside_it():
    """The mandate is a hard constraint: a customer outside it is not this institution's business."""
    from weza.domains.appetite.models import Appetite, AppetiteVersion
    from weza.domains.product.models import ProductVersion

    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == DEMO_BANK)).scalar_one()
        product = db.execute(select(Product).where(Product.institution_id == inst.id)).scalars().first()
        pv = db.get(ProductVersion, product.active_version_id)
        appetite = db.execute(select(Appetite).where(Appetite.institution_id == inst.id,
                                                     Appetite.lifecycle_status == "ACTIVE")).scalars().first()
        assert appetite is not None, "Demo Bank has no active appetite"
        av = db.get(AppetiteVersion, appetite.active_version_id)
        rules = mandate_rules(av)
        assert rules, "the seeded Demo Bank appetite carries no mandate"
        supply = engine.Supply(inst, product, pv, appetite, av)
        weights, _ = __import__("weza.domains.admin_config", fromlist=["get_config"]).get_config(db, "match_weights")
        inside = {"customer_type": "SME", "sector": "retail_trade", "region": "Central", "amount": 5_000_000,
                  "business_age_months": 24, "monthly_turnover": 4_000_000, "documents": []}
        outside = {**inside, "sector": "transport"}
        r_in = engine.evaluate_supply(supply, inside, [], weights)
        r_out = engine.evaluate_supply(supply, outside, [], weights)
    assert not [e for e in r_in["eligibility"] if e["status"] == "FAIL" and e["must"]]
    assert [e for e in r_out["eligibility"] if e["status"] == "FAIL" and e["must"]]


# ------------------------------------------------------------------ 6. consent


def test_consent_is_required_before_an_institution_sees_the_customer(client, as_user):
    """Without a valid consent the institution sees no customer data and may not ask for any."""
    demo_opp, owner = opp_for(DEMO_BANK)
    h = as_user(owner)
    before = client.get(f"/api/v1/inst/opportunities/{demo_opp}", headers=h).json()
    assert before["customer"]["restricted"] is False
    assert before["customer"]["fields"].get("full_name")

    try:
        with session_scope() as db:
            opp = db.get(Opportunity, uuid.UUID(demo_opp))
            consent = db.get(Consent, opp.consent_id)
            consent.status = "WITHDRAWN"
            consent.withdrawn_at = utcnow()
            consent.withdraw_reason = "Withdrawn by the customer (test)"

        after = client.get(f"/api/v1/inst/opportunities/{demo_opp}", headers=h).json()
        assert after["customer"]["restricted"] is True
        assert after["customer"]["fields"] == {}
        assert after["consent"]["status"] == "WITHDRAWN"
        r = client.post(f"/api/v1/inst/opportunities/{demo_opp}/info-requests",
                        json={"kind": "QUESTION", "message": "May I have your business registration?"},
                        headers={**h, **idem(h)})
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == "PRIVACY_VIOLATION"
    finally:  # leave the shared demo data as it was found
        with session_scope() as db:
            opp = db.get(Opportunity, uuid.UUID(demo_opp))
            consent = db.get(Consent, opp.consent_id)
            consent.status = "GRANTED"
            consent.withdrawn_at = None
            consent.withdraw_reason = None


def test_consent_records_what_was_consented_to(client, as_user):
    """The consent carries the what, the who, the when and the status — the auditable record."""
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == DEMO_BANK)).scalar_one()
        opp = db.execute(select(Opportunity).where(Opportunity.institution_id == inst.id).limit(1)).scalar_one()
        c = db.get(Consent, opp.consent_id)
        assert c.status == "GRANTED"
        assert c.institution_id == opp.institution_id
        assert c.customer_id == opp.customer_id
        assert c.need_id == opp.need_id
        assert c.match_id == opp.match_id
        assert c.data_categories, "the consent names no data categories"
        assert c.purpose
        assert c.template_version and c.text_hash
        assert c.granted_at is not None and c.withdrawn_at is None


# ------------------------------------------------------------------ 5. the customer journey


def test_the_journey_reports_a_verified_phone(client, journey):
    """OTP proves the number is reachable — the journey says so, and how."""
    from tests.helpers import SME_ANSWERS

    j = journey("I need UGX 8 million to restock my shop")
    j.send(action="confirm")
    j.verify("0772900117")
    j.answer_profile({**SME_ANSWERS, "identity.nin": "CM1234567890AB"})
    needs = client.get("/api/v1/me/needs", headers=j.customer_headers).json()["needs"]
    assert needs, "the journey has no need"
    need = needs[0]
    assert need["phone_verified"] is True
    assert need["phone_verification_method"] == "OTP"
    assert need["phone_verified_at"]
    assert need["customer_type"] == "SME"
    assert need["amount"] == 8_000_000
    assert need["purpose"]
    assert need["sector"]
    assert need["location"]["district"] == "Kampala"
    assert need["location"]["region"] == "Central"
    assert need["readiness"]


def test_an_unverified_journey_does_not_claim_a_verified_phone():
    """A need that has not been verified says so — the flag is never assumed."""
    from weza.domains.need.models import FinancialNeed

    with session_scope() as db:
        need = db.execute(select(FinancialNeed).where(FinancialNeed.phone_verified.is_(True))).scalars().first()
        assert need is not None, "no verified journey in the seed"
        other = db.execute(select(FinancialNeed).where(FinancialNeed.phone_verified.is_(False))).scalars().first()
        assert other is not None
        assert other.phone_verified_at is None
        assert other.phone_verification_method is None
