"""Indicative terms on reported approvals: validated, labelled as institution-reported, and shown to the customer."""

from datetime import date, timedelta

from tests.helpers import idem, routed_to_lakeside
from weza.platform.events import drain


def _outcome(client, h, oid, **body):
    return client.post(f"/api/v1/inst/opportunities/{oid}/outcome", headers=idem(h), json=body)


def test_approval_with_terms_reaches_customer(client, as_user, journey):
    j, oid, owner = routed_to_lakeside(journey, "0772500001")
    h = as_user(owner)
    valid = (date.today() + timedelta(days=14)).isoformat()
    r = _outcome(client, h, oid, state="REPORTED_APPROVED", approved_amount=18_000_000, tenor_months=24,
                 interest_rate=1.8, rate_period="MONTHLY", fees=250_000, monthly_repayment=925_000,
                 conditions="Subject to site visit", terms_valid_until=valid)
    assert r.status_code == 200, r.text
    terms = r.json()["outcomes"][-1]["terms"]
    assert terms["tenor_months"] == 24 and terms["rate_period"] == "MONTHLY" and terms["valid_until"] == valid
    assert "reported by the institution" in terms["label"]
    drain()

    needs = client.get("/api/v1/me/needs", headers=j.customer_headers).json()["needs"]
    opp = next(o for n in needs for o in n["opportunities"] if o["id"] == oid)
    assert opp["outcomes"][-1]["terms"]["monthly_repayment"] == 925_000
    notes = client.get("/api/v1/me/notifications", headers=j.customer_headers).json()["notifications"]
    assert any("indicative terms" in n["body"] for n in notes)


def test_terms_validation(client, as_user, journey):
    j, oid, owner = routed_to_lakeside(journey, "0772500002")
    h = as_user(owner)
    # Rate without its period
    r = _outcome(client, h, oid, state="REPORTED_APPROVED", approved_amount=10_000_000, interest_rate=20)
    assert r.json()["error"]["code"] == "RATE_PERIOD_REQUIRED"
    # Past validity
    r = _outcome(client, h, oid, state="REPORTED_APPROVED", approved_amount=10_000_000, tenor_months=12,
                 terms_valid_until=(date.today() - timedelta(days=1)).isoformat())
    assert r.json()["error"]["code"] == "TERMS_EXPIRED"
    # Terms only accompany approvals
    r = _outcome(client, h, oid, state="REPORTED_DECLINED", reason_category="AFFORDABILITY", tenor_months=12)
    assert r.json()["error"]["code"] == "TERMS_NOT_ALLOWED"
    # Approval without terms still works and reports none
    r = _outcome(client, h, oid, state="REPORTED_APPROVED", approved_amount=10_000_000)
    assert r.status_code == 200 and r.json()["outcomes"][-1]["terms"] is None
