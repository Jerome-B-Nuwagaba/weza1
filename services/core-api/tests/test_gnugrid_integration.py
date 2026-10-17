"""Just-In-Time gnuGRID CRB: provider pattern, feature flag, lender-selection gate, provenance-tagged facts, audit,
disclosure to the chosen lender, identity-only blocking — all with zero network calls."""

import socket
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

import weza.integrations.gnugrid as gnugrid
from tests.helpers import SME_ANSWERS
from weza.config import Settings
from weza.domains.consent.models import CrbCheck
from weza.domains.customer.models import Customer, Fact
from weza.domains.customer.service import current_facts
from weza.domains.identity.models import User
from weza.domains.institution.models import Institution
from weza.domains.matching.models import ClearingRun
from weza.domains.opportunity.models import Assignment, Opportunity
from weza.domains.trust.models import AuditEvent
from weza.domains.verification.models import IdentityCheck
from weza.platform.db import session_scope, utcnow
from weza.platform.events import drain
from weza.schemas.crb import CRBConsentOTPVerify, CRBConsentRequest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real outbound connection fails the test (the in-process TestClient and libpq don't use these)."""
    def refuse(*a, **k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _lakeside() -> uuid.UUID:
    with session_scope() as db:
        return db.execute(select(Institution.id).where(Institution.display_name == "Lakeside Bank")).scalar_one()


def _selected(journey, phone: str, nin: str | None = None, select_lender: bool = True):
    """A customer who has chosen Lakeside Bank from their options (consent screen showing, nothing shared yet)."""
    j = journey("I need UGX 20 million to buy stock for my pharmacy")
    j.send(action="confirm")
    j.verify(phone)
    j.answer_profile({**SME_ANSWERS, "identity.nin": nin or f"CM{phone}AB"})
    if select_lender:
        opt = next(o for o in j.cards("options")[0]["options"] if o["institution"] == "Lakeside Bank")
        j.send(action="select", value=opt["match_id"])
    return j


def _pull(client, j, otp="123456", institution=None):
    r = client.post("/api/v1/me/crb/consent/request", headers=j.customer_headers,
                    json={"selected_institution_id": str(institution or _lakeside())})
    assert r.status_code == 200, r.text
    ch = r.json()
    return ch, client.post("/api/v1/me/crb/consent/verify", headers=j.customer_headers,
                           json={"session_id": ch["session_id"], "challenge_id": ch["challenge_id"], "otp_code": otp})


def _cid_from_profile(j) -> uuid.UUID:
    from weza.domains.identity import service as identity
    with session_scope() as db:
        return identity.resolve_customer_session(db, j.customer_headers["Authorization"][7:])


# ------------------------------------------------------------------ provider pattern & feature flag


def test_factory_returns_the_mock_by_default_and_the_http_client_only_when_disabled(monkeypatch):
    assert isinstance(gnugrid.get_crb_client(), gnugrid.MockGNUGridClient)
    monkeypatch.setattr(gnugrid, "get_settings", lambda: Settings(gngrid_use_mock=False))
    with pytest.raises(gnugrid.CRBUnavailable):  # not configured -> fails closed, never pretends
        gnugrid.get_crb_client()
    monkeypatch.setattr(gnugrid, "get_settings", lambda: Settings(gngrid_use_mock=False, gnugrid_api_key="k",
                                                                  gnugrid_base_url="https://crb.example"))
    assert isinstance(gnugrid.get_crb_client(), gnugrid.GNUGridHTTPClient)


def test_mock_client_handles_challenge_and_verification_offline():
    c = gnugrid.MockGNUGridClient()
    cid, inst = uuid.uuid4(), uuid.uuid4()

    def run(nin: str, otp: str):
        ch = c.request_consent_otp(CRBConsentRequest(customer_id=cid, national_id=nin, phone_number="+256772000001",
                                                     selected_institution_id=inst))
        assert ch.masked_phone.endswith("001") and "772000" not in ch.masked_phone and ch.expires_in_seconds == 300
        return c.verify_otp_and_pull_summary(CRBConsentOTPVerify(customer_id=cid, session_id=ch.session_id,
                                                                 challenge_id=ch.challenge_id, otp_code=otp,
                                                                 selected_institution_id=inst))
    good = run("CM0772000001AB", "123456")
    assert (good.verification_status, good.credit_score_band, good.numeric_score) == ("VERIFIED", "EXCELLENT", 780)
    bad = run("CM0772000001AB", "000000")
    assert bad.has_active_defaults and bad.credit_score_band == "POOR"
    assert run("CM07720000ZZZZ", "123456").verification_status == "NOT_FOUND"
    with pytest.raises(gnugrid.CRBOTPInvalid):
        run("CM0772000001AB", "999999")


def test_http_client_fails_closed_on_an_unrecognised_report(monkeypatch):
    monkeypatch.setattr(gnugrid, "get_settings", lambda: Settings(gngrid_use_mock=False, gnugrid_api_key="k",
                                                                  gnugrid_base_url="https://crb.example"))
    client = gnugrid.get_crb_client()
    monkeypatch.setattr(client, "_post", lambda path, payload: (200, {"status": "OK", "score": 700}))
    with pytest.raises(gnugrid.CRBUnavailable):
        client.verify_otp_and_pull_summary(CRBConsentOTPVerify(customer_id=uuid.uuid4(), session_id="s",
                                                               challenge_id="c", otp_code="1",
                                                               selected_institution_id=uuid.uuid4()))


def test_production_refuses_the_mock():
    assert any("GNGRID_USE_MOCK" in p for p in Settings(env="production").production_problems())


# ------------------------------------------------------------------ JIT gate


def test_bureau_is_never_called_before_the_customer_selects_that_lender(client, journey, monkeypatch):
    calls = []
    real = gnugrid.MockGNUGridClient.request_consent_otp
    monkeypatch.setattr(gnugrid.MockGNUGridClient, "request_consent_otp",
                        lambda self, req: calls.append(req) or real(self, req))
    j = _selected(journey, "0772480001", select_lender=False)  # options shown, nothing chosen
    r = client.post("/api/v1/me/crb/consent/request", headers=j.customer_headers,
                    json={"selected_institution_id": str(_lakeside())})
    assert r.status_code == 422 and r.json()["error"]["code"] == "LENDER_NOT_SELECTED"
    opt = next(o for o in j.cards("options")[0]["options"] if o["institution"] == "Lakeside Bank")
    j.send(action="select", value=opt["match_id"])
    with session_scope() as db:  # a lender the customer did not choose
        pearl = db.execute(select(Institution.id).where(Institution.display_name == "Pearl SACCO")).scalar_one()
    r = client.post("/api/v1/me/crb/consent/request", headers=j.customer_headers,
                    json={"selected_institution_id": str(pearl)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "LENDER_NOT_SELECTED"
    assert calls == []  # not a single billable call so far
    _pull(client, j)
    assert len(calls) == 1 and calls[0].selected_institution_id == _lakeside()


def test_verified_pull_tags_facts_audits_and_reaches_only_the_chosen_lender(client, as_user, journey):
    j = _selected(journey, "0772480002")
    ch, r = _pull(client, j)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "VERIFIED" and body["report"]["credit_score_band"] == "EXCELLENT"
    cid, lakeside = _cid_from_profile(j), _lakeside()
    with session_scope() as db:
        facts = {k: f for k, f in current_facts(db, cid).items() if k.startswith("crb.")}
        assert set(body["facts_saved"]) == set(facts) and "crb.score_band" in facts
        for f in facts.values():
            assert f.source == "GNGRID_CRB" and f.verification_state == "VERIFIED_THIRD_PARTY" and f.captured_at
            assert f.source_ref == f"crb_check:{ch['check_id']}"
        ev = db.execute(select(AuditEvent).where(AuditEvent.action == "GNGRID_CRB_CONSENT_GRANTED",
                                                 AuditEvent.object_id == ch["check_id"])).scalar_one()
        assert ev.actor_id == str(cid) and ev.institution_id == lakeside and ev.after["status"] == "VERIFIED"
        ic = db.execute(select(IdentityCheck).where(IdentityCheck.customer_id == cid)
                        .order_by(IdentityCheck.created_at.desc())).scalars().first()
        assert ic.provider == "crb_mock" and ic.status == "VERIFIED"
        assert db.get(Customer, cid).verification_level == "IDENTITY"
    drain()
    with session_scope() as db:  # readiness/quality re-cleared from the verified identity
        assert db.execute(select(ClearingRun).where(ClearingRun.trigger_event == "IdentityVerified",
                                                    ClearingRun.trigger_ref == str(cid))).first()

    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    assert j.cards("submitted"), j.texts()
    drain()
    with session_scope() as db:
        o = db.execute(select(Opportunity).where(Opportunity.customer_id == cid)).scalar_one()
        owner = db.get(User, db.get(Assignment, o.id).user_id).email
    view = client.get(f"/api/v1/inst/opportunities/{o.id}", headers=as_user(owner)).json()
    report = view["customer"]["credit_report"]
    assert report["numeric_score"] == 780 and "does not make credit decisions" in report["label"]
    restricted = client.get(f"/api/v1/inst/opportunities/{o.id}", headers=as_user("exec@lakeside.demo")).json()
    assert "credit_report" not in restricted["customer"]


def test_active_defaults_are_shared_but_never_block(client, as_user, journey):
    j = _selected(journey, "0772480003")
    _, r = _pull(client, j, otp="000000")
    assert r.json()["report"]["has_active_defaults"] is True
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    assert j.cards("submitted"), j.texts()  # the lender decides, not WEZA


def test_identity_not_found_blocks_sharing(client, journey):
    j = _selected(journey, "0772480004", nin="CM07724800ZZZZ")
    _, r = _pull(client, j)
    assert r.json()["status"] == "NOT_FOUND" and r.json()["report"] is None
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    assert not j.cards("submitted") and any("credit bureau couldn't confirm" in t for t in j.texts())
    with session_scope() as db:
        assert not db.execute(select(Opportunity).where(Opportunity.customer_id == _cid_from_profile(j))).first()
        assert not db.execute(select(Fact).where(Fact.customer_id == _cid_from_profile(j),
                                                 Fact.key.like("crb.%"))).first()


def test_wrong_code_is_refused_and_an_expired_challenge_closes(client, journey):
    j = _selected(journey, "0772480005")
    ch, r = _pull(client, j, otp="999999")
    assert r.status_code == 422 and r.json()["error"]["code"] == "CRB_OTP_INVALID"
    with session_scope() as db:
        check = db.get(CrbCheck, uuid.UUID(ch["check_id"]))
        assert check.status == "PENDING"
        check.expires_at = utcnow() - timedelta(seconds=1)
    r = client.post("/api/v1/me/crb/consent/verify", headers=j.customer_headers,
                    json={"session_id": ch["session_id"], "challenge_id": ch["challenge_id"], "otp_code": "123456"})
    assert r.json()["status"] == "EXPIRED"
    with session_scope() as db:
        assert db.get(CrbCheck, uuid.UUID(ch["check_id"])).status == "EXPIRED"


def test_with_real_gnugrid_typing_a_nin_triggers_no_billed_call(journey, monkeypatch):
    """JIT: the capture-time registry check is skipped; identity comes with the CRB pull at lender selection."""
    import weza.config
    monkeypatch.setattr(weza.config, "get_settings", lambda: Settings(identity_provider="gnugrid", otp_delivery="display"))
    j = _selected(journey, "0772480006", select_lender=False)
    with session_scope() as db:
        assert not db.execute(select(IdentityCheck).where(IdentityCheck.customer_id == _cid_from_profile(j))).first()


# ------------------------------------------------------------------ cost protection, lender scoping, recovery


def test_no_network_guard_really_blocks():
    with pytest.raises(AssertionError, match="network call attempted"):
        httpx.Client().get("https://api.gnugridcrb.com/health")


def test_a_lender_is_never_billed_twice_for_the_same_customer(client, journey, monkeypatch):
    calls = []
    real = gnugrid.MockGNUGridClient.request_consent_otp
    monkeypatch.setattr(gnugrid.MockGNUGridClient, "request_consent_otp",
                        lambda self, req: calls.append(req) or real(self, req))
    j = _selected(journey, "0772480007")
    body = {"selected_institution_id": str(_lakeside())}
    first = client.post("/api/v1/me/crb/consent/request", headers=j.customer_headers, json=body).json()
    again = client.post("/api/v1/me/crb/consent/request", headers=j.customer_headers, json=body).json()
    assert again["reused"] and again["session_id"] == first["session_id"] and len(calls) == 1  # open challenge reused
    r = client.post("/api/v1/me/crb/consent/verify", headers=j.customer_headers,
                    json={"session_id": first["session_id"], "challenge_id": first["challenge_id"], "otp_code": "1234"})
    assert r.json()["status"] == "VERIFIED"
    later = client.post("/api/v1/me/crb/consent/request", headers=j.customer_headers, json=body).json()
    assert later == {"check_id": first["check_id"], "status": "VERIFIED", "reused": True} and len(calls) == 1
    profile = client.get("/api/v1/me/profile", headers=j.customer_headers)
    assert profile.status_code == 200 and profile.json()["identity"]["status"] == "VERIFIED"


def test_each_lender_sees_only_the_report_pulled_with_its_consent():
    from weza.domains.consent import crb_service
    cid, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with session_scope() as db:
        for inst, score in ((a, 780), (b, 410)):
            db.add(CrbCheck(customer_id=cid, institution_id=inst, provider="mock", session_id="s", challenge_id="c",
                            status="VERIFIED", expires_at=utcnow(), verified_at=utcnow(),
                            summary={"crb_reference_id": f"R{score}", "numeric_score": score}))
    with session_scope() as db:
        assert crb_service.report_for_institution(db, cid, a)["numeric_score"] == 780
        assert crb_service.report_for_institution(db, cid, b)["numeric_score"] == 410
        assert crb_service.report_for_institution(db, cid, uuid.uuid4()) is None


def test_correcting_the_national_id_lifts_a_not_found_block(client, journey):
    j = _selected(journey, "0772480008", nin="CM07724800ZZZZ")
    _, r = _pull(client, j)
    assert r.json()["status"] == "NOT_FOUND"
    r = client.put("/api/v1/me/identity", headers=j.customer_headers, json={"nin": "CM0772480008AB"})
    assert r.status_code == 200, r.text
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    assert j.cards("submitted"), j.texts()
    assert not any("credit bureau couldn't confirm" in t for t in j.texts())
