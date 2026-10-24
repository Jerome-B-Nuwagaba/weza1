"""The Goal 2 activation flow, end to end, through real endpoints only.

The other Goal 2 tests build an institution's supply directly in the database, which is fast but hides a real
trap: an appetite approved while its institution is still in Draft sits at APPROVED, and it can only become
ACTIVE while the institution is ACTIVE. A readiness check that demands a *live* mandate therefore deadlocks —
the institution can never be activated, so its mandate can never go live.

This file drives the whole flow the way the product actually does it — WEZA staff create the institution and
its administrator, the institution's own team builds and approves a product and a mandate, routing is saved,
and WEZA staff then review readiness and activate. Nothing is written to the database behind the API's back.
"""

import uuid

import pytest
from sqlalchemy import select

from tests.helpers import login
from weza.domains.appetite.models import Appetite
from weza.domains.institution.models import Institution
from weza.domains.matching import engine
from weza.platform.db import session_scope

API = "/api/v1/staff"
PW = "WezaDemo!2026"


@pytest.fixture(autouse=True)
def _market_is_restored(clean_market_after):
    """These tests activate real institutions; each one takes its institution back out of the market when it
    finishes, so the seeded market later tests rely on is left alone."""
    yield


@pytest.fixture()
def weza_admin(client):
    """A WEZA user holding the canonical WEZA_ADMIN role."""
    email = f"goal2-flow-admin-{uuid.uuid4().hex[:8]}@weza.demo"
    with session_scope() as db:
        from weza.domains.identity import service as identity
        identity.create_user(db, email=email, full_name="Grace WEZA Admin", password=PW, kind="WEZA",
                             weza_roles=["WEZA_ADMIN"])
    return login(client, email)


def _onboard_institution(client, staff) -> tuple[str, dict]:
    """Staff create a Draft institution and its administrator. Returns (institution id, admin headers)."""
    r = client.post(f"{API}/institutions", headers=staff,
                    json={"legal_name": "Flow Bank Limited", "display_name": "Flow Bank",
                          "institution_type": "Commercial Bank", "licence_no": "BOU/CB/0009-FLOW",
                          "regulator": "Bank of Uganda"})
    assert r.status_code == 201, r.text
    inst_id = r.json()["id"]

    admin_email = f"flow-admin-{uuid.uuid4().hex[:8]}@flow.demo"
    r = client.post(f"{API}/institutions/{inst_id}/administrator", headers=staff,
                    json={"full_name": "Chief Admin", "email": admin_email, "password": "FlowAdmin!Initial2026"})
    assert r.status_code == 201, r.text
    return inst_id, {"admin_email": admin_email, "headers": login(client, admin_email, "FlowAdmin!Initial2026")}


def _build_supply(client, admin) -> None:
    """The institution's own team builds its supply: an officer, a product, a mandate and a routing rule.

    Two people are needed, not one: WEZA separates duties, so whoever authors a product or a mandate cannot
    approve it. The administrator adds a business lead, and the two of them take opposite sides.
    """
    business_email = f"flow-biz-{uuid.uuid4().hex[:8]}@flow.demo"
    r = client.post("/api/v1/inst/users", headers=admin["headers"],
                    json={"full_name": "Business Lead", "email": business_email,
                          "password": "FlowBiz!Initial2026", "roles": ["BUSINESS"]})
    assert r.status_code == 201, r.text
    business = login(client, business_email, "FlowBiz!Initial2026")

    officer_email = f"flow-officer-{uuid.uuid4().hex[:8]}@flow.demo"
    r = client.post("/api/v1/inst/users", headers=admin["headers"],
                    json={"full_name": "Desk Officer", "email": officer_email,
                          "password": "FlowOfficer!Initial2026", "roles": ["OFFICER"]})
    assert r.status_code == 201, r.text

    r = client.post("/api/v1/inst/products", headers=business,
                    json={"name": "Working Capital", "family": "SME_WORKING_CAPITAL",
                          "terms": {"min_amount": 1_000_000, "max_amount": 40_000_000,
                                    "min_tenor_months": 3, "max_tenor_months": 18}})
    assert r.status_code == 201, r.text
    product_id = r.json()["product_id"]
    r = client.post(f"/api/v1/inst/products/{product_id}/submit", headers=business)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/inst/products/{product_id}/review", headers=admin["headers"],
                    json={"approve": True, "note": "Terms checked."})
    assert r.status_code == 200, r.text

    r = client.post("/api/v1/inst/appetites", headers=business,
                    json={"name": "SME Mandate", "product_ids": [product_id]})
    assert r.status_code == 201, r.text
    appetite_id = r.json()["appetite_id"]
    r = client.post(f"/api/v1/inst/appetites/{appetite_id}/simulate", headers=business)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/inst/appetites/{appetite_id}/review", headers=admin["headers"],
                    json={"approve": True, "note": "Mandate agreed."})
    assert r.status_code == 200, r.text

    r = client.put("/api/v1/inst/routing", headers=admin["headers"],
                   json={"rules": [{"name": "Default", "conditions": {}, "active": True}]})
    assert r.status_code == 200, r.text


def _appetite_status(inst_id: str) -> str:
    with session_scope() as db:
        ap = db.execute(select(Appetite).where(Appetite.institution_id == uuid.UUID(inst_id))).scalar_one()
        return ap.lifecycle_status


def _in_market(inst_id: str) -> bool:
    with session_scope() as db:
        wanted = uuid.UUID(inst_id)
        return any(s.institution.id == wanted for s in engine.active_supply(db))


def test_a_staff_created_institution_can_be_driven_all_the_way_to_trading(client, weza_admin):
    """The whole Goal 2 story, with no shortcuts: create, staff the institution, build its supply, review
    readiness, activate, and see the institution trade — then pause it and see it stop trading."""
    inst_id, admin = _onboard_institution(client, weza_admin)

    # A Draft institution is not ready, and cannot trade.
    readiness = client.get(f"{API}/institutions/{inst_id}/readiness", headers=weza_admin).json()
    assert readiness["ready"] is False
    assert _in_market(inst_id) is False

    # Activation is refused while anything is missing, and the refusal names what is missing.
    r = client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin,
                    json={"reason": "Too early."})
    assert r.status_code == 422, r.text
    assert {d["missing"] for d in r.json()["error"]["details"]} == {"officer", "product", "appetite", "routing"}

    # The institution's own team builds the supply.
    _build_supply(client, admin)

    # The mandate is approved but not yet live — the institution is still in Draft.
    assert _appetite_status(inst_id) == "APPROVED"

    # Readiness is now satisfied. This is the step that used to deadlock: a mandate approved while the
    # institution is in Draft is not yet live, and it cannot go live until the institution is active.
    readiness = client.get(f"{API}/institutions/{inst_id}/readiness", headers=weza_admin).json()
    assert readiness["ready"] is True, f"readiness never satisfied: {readiness}"
    assert readiness["missing"] == []

    r = client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin,
                    json={"reason": "Licence verified with the regulator."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ACTIVE"
    assert body["canonical_status"] == "active"
    assert body["readiness"]["ready"] is True

    # The mandate really goes live on activation, and the institution carries active supply.
    assert _appetite_status(inst_id) == "ACTIVE"
    assert _in_market(inst_id) is True

    # Pausing takes it out of the market again.
    r = client.post(f"{API}/institutions/{inst_id}/pause", headers=weza_admin,
                    json={"reason": "Licence renewal under review."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PAUSED"
    assert _in_market(inst_id) is False


def test_a_mandate_approved_while_the_institution_is_active_is_already_live(client, weza_admin):
    """The other order of events: an institution that is already trading gets a new mandate. That mandate is
    live the moment it is approved, and readiness must not pretend otherwise."""
    inst_id, admin = _onboard_institution(client, weza_admin)
    _build_supply(client, admin)
    r = client.post(f"{API}/institutions/{inst_id}/activate", headers=weza_admin,
                    json={"reason": "Ready to trade."})
    assert r.status_code == 200, r.text
    assert _appetite_status(inst_id) == "ACTIVE"

    readiness = client.get(f"{API}/institutions/{inst_id}/readiness", headers=weza_admin).json()
    assert readiness["ready"] is True
    assert next(c for c in readiness["conditions"] if c["key"] == "appetite")["done"] is True
    assert "1 active appetite(s)" == next(c for c in readiness["conditions"] if c["key"] == "appetite")["detail"]
