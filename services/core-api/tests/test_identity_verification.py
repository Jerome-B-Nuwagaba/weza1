"""Applicant identity verification against a registry (gnuGRID; simulator in tests): a typed NIN is only a claim
until the registry confirms it; failures surface to the customer, integrity review and the institution; provider
errors are retried and never count as verified."""

import httpx
import pytest
from sqlalchemy import select

from tests.helpers import SME_ANSWERS, routed_to_lakeside
from weza.config import Settings
from weza.domains.customer.models import Customer, Fact
from weza.domains.misc_models import ReviewItem
from weza.domains.opportunity.models import Opportunity
from weza.domains.verification import adapters
from weza.domains.verification.models import IdentityCheck
from weza.platform.db import session_scope
from weza.platform.events import drain


def _customer_of(opp_id: str) -> Customer:
    with session_scope() as db:
        cid = db.get(Opportunity, opp_id).customer_id
        return db.get(Customer, cid)


def test_simulator_registry_outcomes():
    assert adapters._simulator("CM0772000001AB", "Grace Nakato").status == "VERIFIED"
    assert adapters._simulator("CM07720000ZZZZ", "Grace Nakato").status == "NOT_FOUND"
    assert adapters._simulator("CM0772000001AB", "Grace Mismatch").status == "MISMATCH"
    assert adapters._simulator("", None).status == "ERROR"


def test_gnugrid_mapping_fails_closed(monkeypatch):
    """Until gnuGRID's spec is wired, anything not clearly a match is never 'verified'."""
    m = adapters.map_gnugrid_response
    assert m(200, {"status": "VERIFIED", "name_match": True, "reference": "G1"}).status == "VERIFIED"
    assert m(200, {"status": "VERIFIED", "name_match": False}).status == "MISMATCH"
    assert m(404, {}).status == "NOT_FOUND"
    assert m(200, {"status": "SOMETHING_NEW"}).status == "ERROR"
    monkeypatch.setattr(adapters, "get_settings", lambda: Settings(identity_provider="gnugrid"))
    assert adapters._gnugrid("CM0772000001AB", "Grace").status == "ERROR"  # not configured
    monkeypatch.setattr(adapters, "get_settings", lambda: Settings(
        identity_provider="gnugrid", gnugrid_base_url="https://g.example", gnugrid_api_key="k"))
    calls = []
    monkeypatch.setattr(adapters.httpx, "post", lambda url, **kw: calls.append((url, kw)) or httpx.Response(
        200, json={"status": "MATCH", "name_match": True, "request_id": "R9"}))
    r = adapters._gnugrid("CM0772000001AB", "Grace Nakato")
    assert r.status == "VERIFIED" and r.provider_ref == "R9"
    assert calls[0][0] == "https://g.example/v1/identity/verify"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer k"


def test_captured_nin_is_verified_asynchronously_and_shown_to_institutions(client, as_user, journey):
    j, oid, owner = routed_to_lakeside(journey, "0772700001")  # helper drains the outbox
    with session_scope() as db:
        cid = db.get(Opportunity, oid).customer_id
        check = db.execute(select(IdentityCheck).where(IdentityCheck.customer_id == cid)).scalars().all()[-1]
        assert check.status == "VERIFIED" and check.provider == "simulator"
        assert db.get(Customer, cid).verification_level == "IDENTITY"
        fact = db.execute(select(Fact).where(Fact.customer_id == cid, Fact.key == "identity.nin_captured",
                                             Fact.superseded_at.is_(None))).scalar_one()
        assert fact.verification_state == "VERIFIED" and fact.source == "REGISTRY"
    view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=as_user(owner)).json()
    ident = view["customer"]["verification"]["identity"]
    assert ident["status"] == "VERIFIED" and "verified via" in ident["label"]
    assert view["identity_status"] == "VERIFIED"
    # Executives see the status on the card but never identity data
    exec_view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=as_user("exec@lakeside.demo")).json()
    assert exec_view["identity_status"] == "VERIFIED" and exec_view["customer"]["fields"] == {}
    prof = client.get("/api/v1/me/profile", headers=j.customer_headers).json()
    assert prof["identity"]["status"] == "VERIFIED"


def test_mismatch_and_not_found_raise_signals_and_can_be_corrected(client, as_user, journey):
    j, oid, owner = routed_to_lakeside(journey, "0772700002")
    r = client.put("/api/v1/me/identity", headers=j.customer_headers, json={"full_name": "Grace Mismatch"})
    assert r.status_code == 200 and r.json()["identity"]["status"] == "PENDING"
    drain()
    cust = _customer_of(oid)
    assert cust.verification_level == "PHONE"
    view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=as_user(owner)).json()
    assert view["customer"]["verification"]["identity"]["status"] == "MISMATCH"
    notes = client.get("/api/v1/me/notifications", headers=j.customer_headers).json()["notifications"]
    assert any(n["title"] == "Please check your National ID" for n in notes)
    with session_scope() as db:
        assert db.execute(select(ReviewItem).where(ReviewItem.kind == "IDENTITY_CHECK_FAILED",
                                                   ReviewItem.object_id == oid)).scalars().first()
        from weza.domains.integrity.service import evaluate_customer
        from weza.domains.need.models import FinancialNeed
        need = db.get(FinancialNeed, db.get(Opportunity, oid).need_id)
        _, signals = evaluate_customer(db, db.get(Customer, cust.id), need)
        assert any(s["kind"] == "IDENTITY_MISMATCH" for s in signals)
    # Invalid NIN format is refused; a corrected name re-verifies
    bad = client.put("/api/v1/me/identity", headers=j.customer_headers, json={"nin": "12345"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_NIN"
    client.put("/api/v1/me/identity", headers=j.customer_headers, json={"full_name": "Grace Nakato"})
    drain()
    assert _customer_of(oid).verification_level == "IDENTITY"
    # A NIN the registry doesn't know
    client.put("/api/v1/me/identity", headers=j.customer_headers, json={"nin": "CM07727000ZZZZ"})
    drain()
    assert client.get("/api/v1/me/profile", headers=j.customer_headers).json()["identity"]["status"] == "NOT_FOUND"


def test_provider_errors_are_retried_and_never_verify(client, journey, monkeypatch):
    monkeypatch.setitem(adapters.IDENTITY_PROVIDERS, "simulator",
                        lambda nin, name: adapters.VerificationResult("ERROR", error="registry down"))
    j, oid, _ = routed_to_lakeside(journey, "0772700003")
    with session_scope() as db:
        cid = db.get(Opportunity, oid).customer_id
        assert db.get(Customer, cid).verification_level != "IDENTITY"
        from weza.platform.models import EventDelivery
        d = db.execute(select(EventDelivery).where(EventDelivery.consumer == "identity_verify")
                       .order_by(EventDelivery.next_attempt_at.desc())).scalars().first()
        assert d.status == "PENDING" and d.attempts >= 1 and "registry down" in (d.last_error or "")
    assert client.get("/api/v1/me/profile", headers=j.customer_headers).json()["identity"]["status"] == "PENDING"


def test_sharing_can_require_a_verified_identity(client, journey, monkeypatch):
    """IDENTITY_VERIFICATION_REQUIRED: nothing is shared with an institution until the registry confirms the NIN."""
    import weza.config
    monkeypatch.setattr(weza.config, "get_settings", lambda: Settings(identity_verification_required=True,
                                                                     otp_delivery="display"))
    phone = "0772700004"
    j = journey("I need UGX 20 million to buy stock for my pharmacy")
    j.send(action="confirm")
    j.verify(phone)
    j.answer_profile({**SME_ANSWERS, "identity.nin": f"CM{phone}AB"})
    opt = next(o for o in j.cards("options")[0]["options"] if o["institution"] == "Lakeside Bank")
    j.send(action="select", value=opt["match_id"])
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    assert not j.cards("submitted") and any("confirm your National ID" in t for t in j.texts())
    drain()  # the registry check completes
    opt = next(o for o in j.cards("options")[0]["options"] if o["institution"] == "Lakeside Bank") \
        if j.cards("options") else opt
    j.send(action="select", value=opt["match_id"])
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    assert j.cards("submitted"), j.texts()


@pytest.mark.parametrize("value", ["simulator", "something-else"])
def test_production_rejects_a_fake_registry(value):
    problems = " ".join(Settings(env="production", identity_provider=value).production_problems())
    assert "IDENTITY_PROVIDER" in problems
