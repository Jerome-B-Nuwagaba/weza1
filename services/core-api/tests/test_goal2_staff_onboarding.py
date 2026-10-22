"""WEZA Staff institution onboarding (Goal 2).

The staff flow that brings an institution into the marketplace: list, create in Draft, record the primary
contact, create the administrator, review readiness, activate or pause.

What is asserted here:

* only WEZA staff may use it — an institution administrator, a customer and an anonymous caller get nothing,
  and a WEZA user without the administrator role is refused too;
* an institution is created in Draft and trades nothing until it is activated;
* activation is refused until every readiness condition holds, and the refusal names what is missing;
* every activation and pause is audited;
* an institution that is not ACTIVE cannot receive opportunities; an ACTIVE one can.
"""

import uuid

import pytest
from sqlalchemy import select

from tests.helpers import login
from weza.domains.appetite.models import Appetite, AppetiteVersion
from weza.domains.identity.models import User
from weza.domains.institution.models import Contact, Institution, RoutingRule
from weza.domains.matching import engine
from weza.domains.matching.models import Match
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity import service as opp_svc
from weza.domains.product.models import Product, ProductVersion
from weza.domains.trust.models import AuditEvent
from weza.platform.db import session_scope, utcnow

API = "/api/v1/staff"
PW = "WezaDemo!2026"
_TOKENS: dict[str, dict] = {}


@pytest.fixture(autouse=True)
def _market_is_restored(clean_market_after):
    """These tests activate real institutions; each one takes its institution back out of the market when it
    finishes, so the seeded market later tests rely on is left alone."""
    yield


@pytest.fixture()
def as_user(client):
    """Sign each account in once: the suite shares the per-email sign-in rate limit with other test modules."""
    def _as(email: str) -> dict:
        if email not in _TOKENS:
            _TOKENS[email] = login(client, email)
        return _TOKENS[email]
    return _as


@pytest.fixture()
def weza_admin(client, as_user):
    """A WEZA user holding the canonical WEZA_ADMIN role and nothing else."""
    email = f"weza-admin-{uuid.uuid4().hex[:8]}@weza.demo"
    with session_scope() as db:
        from weza.domains.identity import service as identity
        identity.create_user(db, email=email, full_name="Ada WEZA Admin", password=PW, kind="WEZA",
                             weza_roles=["WEZA_ADMIN"])
    return as_user(email)


# ------------------------------------------------------------------ helpers


def _create(client, headers, **overrides) -> str:
    body = {"legal_name": "Goal Two Bank Limited", "display_name": "Goal Two Bank",
            "institution_type": "Commercial Bank", "licence_no": "BOU/CB/0001-GOAL2",
            "regulator": "Bank of Uganda", "description": "Created by WEZA staff.",
            "website": "https://goal2.demo"}
    body.update(overrides)
    r = client.post(f"{API}/institutions", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_administrator(client, headers, inst_id: str) -> str:
    email = f"admin-{uuid.uuid4().hex[:8]}@goal2.demo"
    r = client.post(f"{API}/institutions/{inst_id}/administrator", headers=headers,
                    json={"full_name": "Chief Admin", "email": email, "password": "GoalTwo!Initial2026"})
    assert r.status_code == 201, r.text
    return email


def _give_supply(inst_id: str, *, routing: bool = True) -> None:
    """Give the institution an active product, an active mandate and a routing rule — the supply a trading
    institution needs. The institution itself builds these through Product and Appetite Studio; the staff
    onboarding flow only has to see that they exist."""
    with session_scope() as db:
        inst = db.get(Institution, uuid.UUID(inst_id))
        product = Product(institution_id=inst.id, name="Working Capital", family="SME_WORKING_CAPITAL",
                          status="ACTIVE")
        db.add(product)
        db.flush()
        version = ProductVersion(product_id=product.id, institution_id=inst.id, version=1, status="APPROVED",
                                 name="Working Capital", family="SME_WORKING_CAPITAL", terms={}, rules=[],
                                 requirements=[], effective_from=utcnow())
        db.add(version)
        db.flush()
        product.active_version_id = version.id
        appetite = Appetite(institution_id=inst.id, name="SME Mandate", lifecycle_status="ACTIVE",
                            capacity_state="ACTIVE")
        db.add(appetite)
        db.flush()
        av = AppetiteVersion(appetite_id=appetite.id, institution_id=inst.id, version=1, status="APPROVED",
                             name="SME Mandate", product_ids=[product.id], criteria=[], min_match_score=60,
                             capacity_limits={}, effective_from=utcnow())
        db.add(av)
        db.flush()
        appetite.active_version_id = av.id
        if routing:
            db.add(RoutingRule(institution_id=inst.id, priority=10, name="Default", conditions={}, active=True))


def _audits(action: str, object_id) -> list[AuditEvent]:
    with session_scope() as db:
        rows = db.execute(select(AuditEvent).where(AuditEvent.action == action,
                                                   AuditEvent.object_id == str(object_id))).scalars().all()
        db.expunge_all()
        return rows


def _status(inst_id: str) -> str:
    with session_scope() as db:
        return db.get(Institution, uuid.UUID(inst_id)).status


# ------------------------------------------------------------------ access


def test_the_staff_area_is_closed_to_everyone_but_weza_staff(client, as_user, weza_admin, journey):
    """An institution administrator, a customer and an anonymous caller get nothing from the staff API."""
    for path in (f"{API}/institutions", f"{API}/institutions/{uuid.uuid4()}"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=as_user("admin@demobank.demo")).status_code == 403, path
    # A customer session is not a staff session.
    j = journey("I need UGX 5 million to restock my shop")
    j.send(action="confirm")
    j.verify("0772900118")
    assert client.get(f"{API}/institutions", headers=j.customer_headers).status_code in (401, 403)
    # The canonical WEZA_ADMIN role is enough.
    assert client.get(f"{API}/institutions", headers=weza_admin).status_code == 200


def test_a_weza_user_without_the_administrator_role_is_refused(client, as_user):
    """WEZA Operations may verify institutions, but only the administrator role may onboard one."""
    for email in ("ops@weza.demo", "commercial@weza.demo"):
        assert client.get(f"{API}/institutions", headers=as_user(email)).status_code == 403, email
        r = client.post(f"{API}/institutions", json={"legal_name": "Refused Bank"}, headers=as_user(email))
        assert r.status_code == 403, email


def test_a_tenant_administrator_cannot_create_an_institution(client, as_user):
    r = client.post(f"{API}/institutions", json={"legal_name": "Sneaky Bank"},
                    headers=as_user("admin@demobank.demo"))
    assert r.status_code == 403
    assert r.json()["error"]["code"] in ("FORBIDDEN", "PERMISSION_DENIED", "ROLE_REQUIRED")


# ------------------------------------------------------------------ create in Draft


def test_staff_create_an_institution_in_draft(client, weza_admin):
    inst_id = _create(client, weza_admin)
    d = client.get(f"{API}/institutions/{inst_id}", headers=weza_admin).json()
    assert d["status"] == "DRAFT"
    assert d["canonical_status"] == "draft"
    assert d["legal_name"] == "Goal Two Bank Limited"
    assert d["readiness"]["ready"] is False
    # It is in the staff list, with its status.
    listed = client.get(f"{API}/institutions", headers=weza_admin).json()["institutions"]
    row = next(i for i in listed if i["id"] == inst_id)
    assert row["status"] == "DRAFT"
    assert row["ready"] is False
    # ...and the creation is audited.
    assert _audits("institution.draft_created", inst_id)


def test_the_institution_name_is_required(client, weza_admin):
    r = client.post(f"{API}/institutions", json={"legal_name": "  "}, headers=weza_admin)
    assert r.status_code in (400, 422), r.text


# ------------------------------------------------------------------ primary contact


def test_staff_record_the_primary_contact(client, weza_admin):
    inst_id = _create(client, weza_admin)
    r = client.put(f"{API}/institutions/{inst_id}/contact", headers=weza_admin,
                   json={"name": "Priya Head", "email": "priya@goal2.demo", "phone": "+256700000001",
                         "title": "Head of Credit"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["primary_contact"]["email"] == "priya@goal2.demo"
    assert d["primary_contact"]["is_primary"] is True
    assert _audits("institution.primary_contact_set", inst_id)

    # Setting it again replaces it, and there is still exactly one primary contact.
    r = client.put(f"{API}/institutions/{inst_id}/contact", headers=weza_admin,
                   json={"name": "Priya Head", "email": "priya.h@goal2.demo"})
    assert r.status_code == 200, r.text
    with session_scope() as db:
        primaries = db.execute(select(Contact).where(Contact.institution_id == uuid.UUID(inst_id),
                                                    Contact.is_primary.is_(True))).scalars().all()
        assert len(primaries) == 1
        assert primaries[0].email == "priya.h@goal2.demo"


def test_the_primary_contact_needs_a_name_and_an_email(client, weza_admin):
    inst_id = _create(client, weza_admin)
    r = client.put(f"{API}/institutions/{inst_id}/contact", headers=weza_admin, json={"name": "", "email": ""})
    assert r.status_code in (400, 422), r.text


# ------------------------------------------------------------------ the administrator


def test_staff_create_the_institution_administrator(client, weza_admin):
    inst_id = _create(client, weza_admin)
    email = _add_administrator(client, weza_admin, inst_id)
    # The account is a normal institution user: it signs in and reaches its own workspace.
    h = login(client, email, "GoalTwo!Initial2026")
    ws = client.get("/api/v1/inst/workspace", headers=h).json()
    assert ws["institution"]["id"] == inst_id
    assert "users.manage" in ws["permissions"]
    # The creation is audited against the new user.
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        assert _audits("institution.administrator_created", user.id)


def test_the_administrator_password_must_be_strong_enough(client, weza_admin):
    inst_id = _create(client, weza_admin)
    r = client.post(f"{API}/institutions/{inst_id}/administrator", headers=weza_admin,
                    json={"full_name": "Weak", "email": "weak@goal2.demo", "password": "short"})
    assert r.status_code in (400, 422), r.text


def test_the_administrator_is_counted_by_the_readiness_check(client, weza_admin):
    inst_id = _create(client, weza_admin)
    r = client.get(f"{API}/institutions/{inst_id}/readiness", headers=weza_admin).json()
    assert r["ready"] is False
    assert r["missing"] == ["administrator", "product", "appetite", "routing"]
    _add_administrator(client, weza_admin, inst_id)
    r = client.get(f"{API}/institutions/{inst_id}/readiness", headers=weza_admin).json()
    assert r["missing"] == ["product", "appetite", "routing"]
    assert next(c for c in r["conditions"] if c["key"] == "administrator")["done"] is True


# ------------------------------------------------------------------ activation


def test_activation_is_refused_until_every_condition_holds(client, weza_admin):
    inst_id = _create(client, weza_admin)
    r = client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin,
                    json={"reason": "Everything is ready."})
    assert r.status_code == 422, r.text
    body = r.json()["error"]
    assert body["code"] == "ACTIVATION_NOT_READY"
    assert {d["missing"] for d in body["details"]} == {"administrator", "product", "appetite", "routing"}
    assert _status(inst_id) == "DRAFT"

    # One condition short: still refused, and the refusal names it.
    _add_administrator(client, weza_admin, inst_id)
    _give_supply(inst_id, routing=False)
    r = client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin,
                    json={"reason": "Almost."})
    assert r.status_code == 422, r.text
    assert {d["missing"] for d in r.json()["error"]["details"]} == {"routing"}
    assert _status(inst_id) == "DRAFT"


def test_activation_activates_the_institution_and_is_audited(client, weza_admin):
    inst_id = _create(client, weza_admin)
    _add_administrator(client, weza_admin, inst_id)
    _give_supply(inst_id)
    r = client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin,
                    json={"reason": "Licence checked with the regulator."})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "ACTIVE"
    assert d["canonical_status"] == "active"
    assert d["readiness"]["ready"] is True
    assert d["activation"]["activated_at"]

    # Every step of the lifecycle is audited, and so is the activation itself.
    assert _audits("institution.draft_created", inst_id)
    assert _audits("institution.approved", inst_id)
    assert _audits("institution.active", inst_id)
    assert _audits("institution.activated_by_staff", inst_id)
    event = _audits("institution.active", inst_id)[0]
    assert event.reason == "Licence checked with the regulator."
    assert event.actor_display == "Ada WEZA Admin"


def test_a_paused_institution_can_be_brought_back(client, weza_admin):
    inst_id = _create(client, weza_admin)
    _add_administrator(client, weza_admin, inst_id)
    _give_supply(inst_id)
    client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin, json={"reason": "Ready to trade."})
    r = client.post(f"{API}/institutions/{inst_id}/pause", headers=weza_admin,
                    json={"reason": "Licence renewal under review."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PAUSED"
    assert r.json()["canonical_status"] == "paused"
    assert _audits("institution.paused_by_staff", inst_id)
    assert _audits("institution.paused", inst_id)

    r = client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin,
                    json={"reason": "Licence renewed."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ACTIVE"


def test_only_an_active_institution_can_be_paused(client, weza_admin):
    inst_id = _create(client, weza_admin)
    r = client.post(f"{API}/institutions/{inst_id}/pause", headers=weza_admin, json={"reason": "Too early."})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "NOT_ACTIVE"


def test_an_activation_needs_a_reason(client, weza_admin):
    inst_id = _create(client, weza_admin)
    r = client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin, json={"reason": ""})
    assert r.status_code in (400, 422), r.text


# ------------------------------------------------------------------ opportunities


def test_an_inactive_institution_cannot_receive_opportunities_but_an_active_one_can(client, weza_admin):
    """The market only carries ACTIVE institutions. A Draft one is invisible to customers; once activated it
    can receive opportunities; once paused it disappears again."""
    inst_id = _create(client, weza_admin)
    _add_administrator(client, weza_admin, inst_id)
    _give_supply(inst_id)
    wanted = uuid.UUID(inst_id)

    def in_market() -> bool:
        with session_scope() as db:
            return any(s.institution.id == wanted for s in engine.active_supply(db))

    assert in_market() is False, "a Draft institution must not be in the market"
    client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin, json={"reason": "Ready to trade."})
    assert in_market() is True, "an ACTIVE institution must be in the market"
    client.post(f"{API}/institutions/{inst_id}/pause", headers=weza_admin,
                json={"reason": "Under regulatory review."})
    assert in_market() is False, "a paused institution must not be in the market"


def test_an_opportunity_cannot_be_routed_to_an_inactive_institution(client, weza_admin):
    """The gate that protects a customer: an opportunity for an institution that is not ACTIVE is refused and
    the customer is sent back to the market."""
    inst_id = _create(client, weza_admin)
    _add_administrator(client, weza_admin, inst_id)
    _give_supply(inst_id)

    with session_scope() as db:
        need = db.execute(select(FinancialNeed).where(FinancialNeed.customer_id.is_not(None)).limit(1)).scalar_one()
        product = db.execute(select(Product).where(Product.synthetic.is_(False),
                                                 Product.active_version_id.is_not(None)).limit(1)).scalar_one()
        match = Match(need_id=need.id, institution_id=uuid.UUID(inst_id), product_id=product.id,
                      product_version_id=product.active_version_id, state="RANKED", readiness="READY")
        db.add(match)
        db.flush()
        match_id = match.id
    with session_scope() as db:
        m = db.get(Match, match_id)
        with pytest.raises(opp_svc.RematchRequired) as err:
            opp_svc.validate_match(db, m)
        assert err.value.reason == "institution_inactive"
