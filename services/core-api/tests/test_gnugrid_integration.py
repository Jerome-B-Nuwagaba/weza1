"""Just-In-Time gnuGRID CRB (GnuGrid Enquiries API v1.08): the real client's request contract and response mapping,
the identity rules, cost protection (never pay twice), the lender-selection gate, the journey step with explicit
consent, provenance-tagged facts, audit, disclosure to the chosen lender only, and identity-only blocking.
All with zero network calls: the real client runs against a recording fake; the journey uses the offline bureau."""

import socket
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, update

import weza.integrations.gnugrid as gnugrid
from tests.helpers import SME_ANSWERS
from weza.config import Settings, get_settings
from weza.domains.consent import crb_service
from weza.domains.consent.models import CrbCheck
from weza.domains.customer.models import Customer, Fact
from weza.domains.customer.service import current_facts
from weza.domains.identity.models import User
from weza.domains.institution.models import Institution
from weza.domains.misc_models import ReviewItem
from weza.domains.need.models import ConversationMessage
from weza.domains.opportunity.models import Assignment, Opportunity
from weza.domains.trust.models import AuditEvent
from weza.domains.verification.models import IdentityCheck
from weza.platform.db import session_scope, utcnow
from weza.platform.events import drain
from weza.schemas.crb import CrbEnquiry, CrbProfile

BASE = "https://crb-test.gnugrid.example/api"
REAL = dict(env="production", gngrid_use_mock=False, gnugrid_base_url=BASE, gnugrid_client_id="FAKE_client",
            gnugrid_client_secret="FAKE_secret", gnugrid_enquiry_reason="For loan application")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real outbound connection fails the test (the in-process TestClient and libpq don't use these)."""
    def refuse(*a, **k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    gnugrid._tokens.clear()
    gnugrid.MOCK_BUREAU.calls.clear()


@pytest.fixture
def crb_on(monkeypatch):
    """The journey asks for the bureau check (offline mock bureau)."""
    monkeypatch.setattr(get_settings(), "crb_jit_enabled", True)


# ------------------------------------------------------------------ a fake GnuGrid speaking the spec's JSON


class _R:
    def __init__(self, status, data):
        self.status_code, self._d = status, data

    def json(self):
        return self._d


SPEC_ENQUIRY = {"message": "success", "status": 200, "count": 9, "enquiry": {
    "id": "57ca4cd1-db40-4d37-bebf-92fd5dc7a7ab", "entity": "Individual", "timestamp": "2022-06-03 04:10:55",
    "reference": "DBFREEYXQLUWURF", "criteria": "identifier", "search_value": "4937XX1QVASDF",
    "identification_type": "Country ID Number", "status": "SUCCESSFUL", "cost": 0,
    "formal": {"matches": 1, "sector": "formal", "individuals": [
        {"individual_id": 12965, "image": "", "surname": "OKELLO", "forename1": "JOHN", "forename2": "BOSCO",
         "forename3": "KEN", "gender": "Male", "date_of_birth": "1993-03-31", "nationality": "Ugandan"}]},
    "informal": {"matches": 1, "sector": "formal", "individuals": [
        {"individual_id": 1345, "image": "", "surname": "OKELLO", "forename1": "JOHN", "forename2": "BOSCO",
         "forename3": "KEN", "gender": "Male", "date_of_birth": "1993-03-31", "nationality": "Ugandan"}]}}}
SPEC_REPORT = {"message": "success", "status": 200, "count": 21, "credit_information": {
    "customer_details": {"Photo": "base64_image_string", "Name": "FULL NAME", "Contact": "Tel: 256702000000"},
    "scoring_details": {"Evaluation_Period": "February 2023", "Current_Score": 722, "Current_Score_Band": "AAA",
                        "Current_Score_Rating": "Excellent", "Probability_of_Default": "6.25%"},
    "credit_accounts_summary": [
        {"Total_Credit_Accounts": 2, "Open_Accounts": 1, "Closed_Accounts": 1, "Adverse_Accounts": 0,
         "Worst_Days_in_Arreas": 95},
        {"Credit_Accounts": [{"Currency": "UGX", "Loan_Amount": 29000000, "Loan_Balance": "949090.00",
                              "Amount_Overdue": "0.00"}]}]}}


class FakeGnuGrid:
    def __init__(self, enquiry=None, report=None):
        self.calls, self.enquiry, self.report = [], enquiry or SPEC_ENQUIRY, report or SPEC_REPORT
        self.token_status, self.enquiry_status, self.enquiry_error = 200, 200, None
        self.fail_first_enquiry_with_401 = False

    def __call__(self, url, json, headers, timeout):  # noqa: A002 — mirrors httpx.post
        self.calls.append((url, json, headers))
        if url.endswith("/v1/oauth/token"):
            if self.token_status != 200:
                return _R(self.token_status, {"error": "invalid_client", "error_description": "Client authentication "
                                                                                              "failed"})
            return _R(200, {"token_type": "Bearer", "expires_in": 3600, "access_token": f"tok{len(self.calls)}"})
        if url.endswith("/v1/credit-enquiries/request/new"):
            if self.fail_first_enquiry_with_401:
                self.fail_first_enquiry_with_401 = False
                return _R(401, {"status": "error", "message": "Unauthenticated", "code": 401})
            if self.enquiry_error:
                raise self.enquiry_error
            return _R(self.enquiry_status, self.enquiry)
        if url.endswith("/v1/credit-enquiries/individual/credit-report"):
            return _R(200, self.report)
        return _R(405, {"status": "error", "message": "Method is not allowed for the requested route"})

    def paths(self):
        return [u.replace(BASE, "") for u, _, _ in self.calls]


@pytest.fixture
def fake(monkeypatch):
    s = get_settings()
    for k, v in REAL.items():
        monkeypatch.setattr(s, k, v)
    bureau = FakeGnuGrid()
    monkeypatch.setattr(gnugrid.GNUGridHTTPClient, "_post",
                        lambda self, url, body, headers: bureau(url, body, headers, self.timeout))
    return bureau


# ------------------------------------------------------------------ client contract (v1.08)


def test_factory_uses_the_mock_by_default_and_the_real_client_only_when_fully_configured(monkeypatch):
    assert isinstance(gnugrid.get_crb_client(), gnugrid.MockGNUGridClient)
    monkeypatch.setattr(gnugrid, "get_settings", lambda: Settings(env="test", gngrid_use_mock=False))
    assert isinstance(gnugrid.get_crb_client(), gnugrid.MockGNUGridClient)
    monkeypatch.setattr(gnugrid, "get_settings", lambda: Settings(env="production", gngrid_use_mock=False))
    with pytest.raises(gnugrid.CRBConfigError) as exc:  # not configured -> fails closed, names what's missing
        gnugrid.get_crb_client()
    assert "GNUGRID_CLIENT_ID" in str(exc.value) and "GNUGRID_CLIENT_SECRET" in str(exc.value)
    monkeypatch.setattr(gnugrid, "get_settings", lambda: Settings(**{**REAL, "gnugrid_base_url": "http://x"}))
    with pytest.raises(gnugrid.CRBConfigError, match="https"):
        gnugrid.get_crb_client()
    monkeypatch.setattr(gnugrid, "get_settings", lambda: Settings(**REAL))
    assert type(gnugrid.get_crb_client()) is gnugrid.GNUGridHTTPClient


def test_real_client_sends_exactly_the_documented_requests(fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "gnugrid_pi_code", "PI001")
    client = gnugrid.get_crb_client()
    enquiry = client.credit_enquiry("CM93041234567A", claimed_name="John Okello")
    report = client.credit_report(enquiry.enquiry_id, enquiry.profiles[0].individual_id, reference=enquiry.reference)
    assert fake.paths() == ["/v1/oauth/token", "/v1/credit-enquiries/request/new",
                            "/v1/credit-enquiries/individual/credit-report"]  # one token, reused
    (_, tok, _), (_, enq, enq_h), (_, rep, rep_h) = fake.calls
    assert tok == {"grant_type": "client_credentials", "client_id": "FAKE_client", "client_secret": "FAKE_secret"}
    assert enq == {"identifier": "CM93041234567A", "entity_type": 0, "identification_type": "ii_country_id",
                   "reason": "For loan application", "client_consented": "Yes", "pi_code": "PI001"}
    assert rep == {"enquiry_id": "57ca4cd1-db40-4d37-bebf-92fd5dc7a7ab", "individual_id": 12965, "format": "json"}
    assert enq_h["Authorization"] == rep_h["Authorization"] == "Bearer tok1" and enq_h["Content-Type"] == "application/json"
    assert (enquiry.reference, enquiry.bureau_status, enquiry.matches) == ("DBFREEYXQLUWURF", "SUCCESSFUL",
                                                                           {"formal": 1, "informal": 1})
    assert (report.numeric_score, report.credit_score_band, report.score_grade) == (722, "EXCELLENT", "AAA")
    assert (report.active_loans_count, report.total_outstanding_balance_ugx, report.worst_days_in_arrears) == (1, 949090.0,
                                                                                                              95)
    assert report.has_active_defaults is False and report.probability_of_default == "6.25%"
    assert "Photo" not in str(report.model_dump()) and "256702" not in str(report.model_dump())  # raw data never kept


def test_expired_token_is_refreshed_once(fake):
    fake.fail_first_enquiry_with_401 = True
    gnugrid.get_crb_client().credit_enquiry("CM93041234567A")
    assert fake.paths() == ["/v1/oauth/token", "/v1/credit-enquiries/request/new", "/v1/oauth/token",
                            "/v1/credit-enquiries/request/new"]


def test_bad_credentials_and_billing_errors_need_operations_not_retries(fake):
    fake.token_status = 401
    with pytest.raises(gnugrid.CRBConfigError) as exc:
        gnugrid.get_crb_client().credit_enquiry("CM93041234567A")
    assert exc.value.category == "AUTH"
    fake.token_status, fake.enquiry_status = 200, 403
    fake.enquiry = {"subscription": "INSUFFICIENT ", "message": "Your institution account has insufficient funds"}
    with pytest.raises(gnugrid.CRBConfigError) as exc:
        gnugrid.get_crb_client().credit_enquiry("CM93041234567A")
    assert (exc.value.category, exc.value.billing_state) == ("BILLING", "INSUFFICIENT")


def test_a_timeout_after_sending_is_uncertain_and_never_resent(fake):
    fake.enquiry_error = httpx.ReadTimeout("slow")
    with pytest.raises(gnugrid.CRBUncertain):
        gnugrid.get_crb_client().credit_enquiry("CM93041234567A")
    assert fake.paths().count("/v1/credit-enquiries/request/new") == 1
    fake.enquiry_error = httpx.ConnectError("refused")  # never left: one immediate retry, then unavailable
    with pytest.raises(gnugrid.CRBUnavailable):
        gnugrid.get_crb_client().credit_enquiry("CM93041234567A")
    assert fake.paths().count("/v1/credit-enquiries/request/new") == 3


def test_an_unreadable_paid_answer_is_uncertain(fake):
    fake.enquiry = {"message": "success", "status": 200}
    with pytest.raises(gnugrid.CRBUncertain):
        gnugrid.get_crb_client().credit_enquiry("CM93041234567A")


def test_report_mapping_flags_adverse_accounts_and_arrears():
    r = gnugrid.parse_report({"credit_information": {
        "scoring_details": {"Current_Score": "410", "Current_Score_Rating": "Very Poor", "Current_Score_Band": "CC"},
        "credit_accounts_summary": [{"Open_Accounts": 2, "Adverse_Accounts": 1},
                                    {"Credit_Accounts": [{"Currency": "UGX", "Loan_Balance": "6,500,000.00",
                                                          "Amount_Overdue": "850000.00"},
                                                         {"Currency": "USD", "Loan_Balance": "900.00"}]}]}}, "R1")
    assert (r.numeric_score, r.credit_score_band, r.active_loans_count) == (410, "POOR", 2)
    assert r.has_active_defaults and r.total_outstanding_balance_ugx == 6_500_000.0  # UGX only
    odd = gnugrid.parse_report({"credit_information": {"scoring_details": {"Current_Score_Rating": "Stellar"}}}, "R2")
    assert odd.credit_score_band is None and odd.has_active_defaults is False


def _enq(*people, status="SUCCESSFUL", matches=None):
    profiles = [CrbProfile(sector=s, individual_id=str(i), surname=sn, forenames=fn) for i, (s, sn, fn) in
                enumerate(people, 1)]
    return CrbEnquiry(enquiry_id="E", bureau_status=status, matches=matches or {"formal": 1 if people else 0},
                      profiles=profiles)


def test_identity_rules():
    one = _enq(("formal", "OKELLO", ["JOHN", "BOSCO"]))
    assert crb_service.interpret(one, "Bosco Okello")[0] == "VERIFIED"  # order and case ignored
    assert crb_service.interpret(one, "John Mukasa")[0] == "MISMATCH"
    assert crb_service.interpret(one, None)[0] == "AMBIGUOUS"
    assert crb_service.interpret(_enq(), "John Okello")[0] == "NOT_FOUND"
    assert crb_service.interpret(_enq(("formal", "OKELLO", ["JOHN"]), status="PENDING"), "John Okello")[0] == "PENDING"
    two = _enq(("formal", "OKELLO", ["JOHN"]), ("formal", "OKELLO", ["JOHN"]), matches={"formal": 2})
    assert crb_service.interpret(two, "John Okello")[0] == "AMBIGUOUS"
    disagree = _enq(("formal", "OKELLO", ["JOHN"]), ("informal", "MUKASA", ["PETER"]),
                    matches={"formal": 1, "informal": 1})
    assert crb_service.interpret(disagree, "John Okello")[0] == "AMBIGUOUS"


def test_production_refuses_the_mock_and_names_missing_crb_settings():
    assert any("GNGRID_USE_MOCK" in p for p in Settings(env="production").production_problems())
    problems = Settings(env="production", gngrid_use_mock=False).production_problems()
    assert any("GNUGRID_CLIENT_SECRET" in p for p in problems)
    assert not any("CRB" in p for p in Settings(**REAL).production_problems())


# ------------------------------------------------------------------ journey: lender gate, explicit consent, outcomes


def _lakeside() -> uuid.UUID:
    with session_scope() as db:
        return db.execute(select(Institution.id).where(Institution.display_name == "Lakeside Bank")).scalar_one()


@pytest.fixture(autouse=True)
def quiet_integrity_history():
    """These journeys all start with the same sentence from the same test client. Every other test module does too, so
    in a full run the marketplace-integrity "same message" and "same device" patterns would fire for a perfectly
    ordinary customer and hold the request. History from earlier tests is moved out of the pattern windows."""
    with session_scope() as db:
        db.execute(update(Customer).values(device_hash=None))
        db.execute(update(ConversationMessage).where(ConversationMessage.received_at >= utcnow() - timedelta(days=1))
                   .values(received_at=utcnow() - timedelta(days=3)))
    yield


def _selected(journey, phone: str, nin: str | None = None, name: str = "Grace Nakato", select_lender: bool = True):
    """A customer who has chosen Lakeside Bank from their options (consent screen showing, nothing shared yet)."""
    j = journey("I need UGX 20 million to buy stock for my pharmacy")
    j.send(action="confirm")
    j.verify(phone)
    j.answer_profile({**SME_ANSWERS, "identity.full_name": name, "identity.nin": nin or f"CM{phone}AB"})
    if select_lender:
        opt = next(o for o in j.cards("options")[0]["options"] if o["institution"] == "Lakeside Bank")
        j.send(action="select", value=opt["match_id"])
    return j


def _agree(j, crb: str | None = "yes"):
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    if crb:
        assert any("credit reference bureau" in t for t in j.texts()), j.texts()
        j.send(action="crb_consent", value=crb)
        if crb == "yes" and j.cards("otp_input") and j.cards("otp_input")[-1].get("purpose") == "crb":
            j.send(j.cards("otp_input")[-1]["dev_code"])
    return j


def _cid(j) -> uuid.UUID:
    from weza.domains.identity import service as identity
    with session_scope() as db:
        return identity.resolve_customer_session(db, j.customer_headers["Authorization"][7:])


def _checks(cid) -> list[CrbCheck]:
    with session_scope() as db:
        rows = db.execute(select(CrbCheck).where(CrbCheck.customer_id == cid).order_by(CrbCheck.created_at)).scalars()
        out = list(rows)
        db.expunge_all()
        return out


def _check_body(client, j):
    body = {"selected_institution_id": str(_lakeside()), "consent": True}
    result = client.post("/api/v1/me/crb/challenge", headers=j.customer_headers, json=body)
    assert result.status_code == 200, result.text
    challenge = result.json()
    return {**body, "challenge_id": challenge["challenge_id"], "otp": challenge["dev_code"]}


def test_journey_has_no_bureau_step_while_it_is_disabled(journey):
    j = _agree(_selected(journey, "0772480010"), crb=None)
    assert j.cards("submitted") and gnugrid.MOCK_BUREAU.enquiries == []


def test_bureau_is_never_called_before_the_customer_chooses_that_lender(client, journey, crb_on):
    j = _selected(journey, "0772480001", select_lender=False)  # options shown, nothing chosen
    r = client.post("/api/v1/me/crb/check", headers=j.customer_headers,
                    json={"selected_institution_id": str(_lakeside()), "consent": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "LENDER_NOT_SELECTED"
    r = client.post("/api/v1/me/crb/check", headers=j.customer_headers,
                    json={"selected_institution_id": str(_lakeside()), "consent": False})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CRB_CONSENT_REQUIRED"
    assert gnugrid.MOCK_BUREAU.enquiries == []  # not a single billable call so far


def test_verified_check_tags_facts_audits_and_reaches_only_the_chosen_lender(client, as_user, journey, crb_on):
    j = _agree(_selected(journey, "0772480002"))
    assert any("match the credit bureau record" in t for t in j.texts()) and j.cards("submitted"), j.texts()
    assert len(gnugrid.MOCK_BUREAU.enquiries) == 1
    assert gnugrid.MOCK_BUREAU.enquiries[0]["client_consented"] == "Yes"
    cid, lakeside = _cid(j), _lakeside()
    [check] = _checks(cid)
    assert (check.status, check.institution_id, check.consent_version) == ("VERIFIED", lakeside,
                                                                           crb_service.CONSENT_VERSION)
    assert check.consent_text_hash == crb_service.consent_hash("Lakeside Bank") and check.consented_at
    assert check.enquiry_id and check.enquiry_reference and check.individual_id
    with session_scope() as db:
        facts = {k: f for k, f in current_facts(db, cid).items() if k.startswith("crb.")}
        assert "crb.score_band" in facts
        for f in facts.values():
            assert f.source == "GNGRID_CRB" and f.verification_state == "VERIFIED_THIRD_PARTY"
            assert f.source_ref == f"crb_check:{check.id}"
        ev = db.execute(select(AuditEvent).where(AuditEvent.action == "GNGRID_CRB_CHECK_COMPLETED",
                                                 AuditEvent.object_id == str(check.id))).scalar_one()
        assert ev.actor_id == str(cid) and ev.institution_id == lakeside and ev.after["status"] == "VERIFIED"
        ic = db.execute(select(IdentityCheck).where(IdentityCheck.customer_id == cid)
                        .order_by(IdentityCheck.created_at.desc())).scalars().first()
        assert ic.provider == "crb_mock" and ic.status == "VERIFIED"
        assert db.get(Customer, cid).verification_level == "IDENTITY"
    drain()
    with session_scope() as db:
        o = db.execute(select(Opportunity).where(Opportunity.customer_id == cid)).scalar_one()
        owner = db.get(User, db.get(Assignment, o.id).user_id).email
    report = client.get(f"/api/v1/inst/opportunities/{o.id}", headers=as_user(owner)).json()["customer"]["credit_report"]
    assert report["numeric_score"] == 780 and "does not make credit decisions" in report["label"]
    restricted = client.get(f"/api/v1/inst/opportunities/{o.id}", headers=as_user("exec@lakeside.demo")).json()
    assert "credit_report" not in restricted["customer"]


def test_saying_no_skips_the_bureau_and_still_shares(journey, crb_on):
    j = _agree(_selected(journey, "0772480011"), crb="no")
    assert j.cards("submitted") and gnugrid.MOCK_BUREAU.enquiries == [] and _checks(_cid(j)) == []


def test_active_defaults_are_shared_but_never_block(journey, crb_on):
    j = _agree(_selected(journey, "0772480003", nin="CM0772480003DD"))
    assert j.cards("submitted"), j.texts()  # the lender decides, not WEZA
    assert _checks(_cid(j))[0].summary["has_active_defaults"] is True


def test_identity_not_found_blocks_sharing(journey, crb_on):
    j = _agree(_selected(journey, "0772480004", nin="CM0772480004ZZ"))
    assert not j.cards("submitted") and any("credit bureau couldn't confirm" in t for t in j.texts())
    cid = _cid(j)
    with session_scope() as db:
        assert not db.execute(select(Opportunity).where(Opportunity.customer_id == cid)).first()
        assert not db.execute(select(Fact).where(Fact.customer_id == cid, Fact.key.like("crb.%"))).first()


def test_name_mismatch_blocks_and_goes_to_review(journey, crb_on):
    j = _agree(_selected(journey, "0772480012", name="Grace Mismatch"))
    assert not j.cards("submitted")
    [check] = _checks(_cid(j))
    assert check.status == "MISMATCH" and check.summary is None
    with session_scope() as db:
        assert db.execute(select(ReviewItem).where(ReviewItem.dedupe_key == f"IDENTITY_UNVERIFIED:{check.id}")).first()


@pytest.mark.parametrize("suffix,status,review", [("MM", "AMBIGUOUS", "IDENTITY_UNVERIFIED"),
                                                  ("PP", "UNRESOLVED", "CRB_CHECK_UNRESOLVED")])
def test_ambiguous_or_pending_never_block_and_go_to_review(journey, crb_on, suffix, status, review):
    phone = "07724800" + ("13" if suffix == "MM" else "14")
    j = _agree(_selected(journey, phone, nin=f"CM{phone}{suffix}"))
    assert j.cards("submitted"), j.texts()
    [check] = _checks(_cid(j))
    assert check.status == status and check.summary is None
    with session_scope() as db:
        assert db.execute(select(ReviewItem).where(ReviewItem.dedupe_key == f"{review}:{check.id}")).first()


def test_no_float_alerts_operations_and_the_request_continues(journey, crb_on):
    j = _agree(_selected(journey, "0772480015", nin="CM0772480015BB"))
    assert j.cards("submitted") and any("couldn't be completed" in t for t in j.texts())
    [check] = _checks(_cid(j))
    assert (check.status, check.error_category) == ("FAILED", "BILLING")
    with session_scope() as db:
        alert = db.execute(select(ReviewItem).where(ReviewItem.dedupe_key == "CRB_UNAVAILABLE:BILLING")).scalar_one()
        assert alert.severity == "HIGH"


# ------------------------------------------------------------------ cost protection


def test_a_lender_is_never_billed_twice_for_the_same_customer(client, journey, crb_on):
    j = _selected(journey, "0772480007")
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    body = _check_body(client, j)
    results = [client.post("/api/v1/me/crb/check", headers=j.customer_headers, json=body).json() for _ in range(3)]
    assert [r["status"] for r in results] == ["VERIFIED"] * 3 and results[1]["reused"] and results[2]["reused"]
    assert len(gnugrid.MOCK_BUREAU.enquiries) == 1  # replayed three times, charged once
    j.send(action="crb_consent", value="yes")  # the journey reuses it too
    assert j.cards("submitted") and len(gnugrid.MOCK_BUREAU.enquiries) == 1


def test_a_failed_report_resumes_with_the_paid_enquiry(client, journey, crb_on, monkeypatch):
    real = gnugrid.GNUGridClient.credit_report

    def down(self, *a, **k):
        raise gnugrid.CRBUnavailable("UNAVAILABLE", "report endpoint down")
    monkeypatch.setattr(gnugrid.GNUGridClient, "credit_report", down)
    j = _selected(journey, "0772480016")
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    body = _check_body(client, j)
    first = client.post("/api/v1/me/crb/check", headers=j.customer_headers, json=body).json()
    assert first["status"] == "ENQUIRED" and first["report"] is None
    monkeypatch.setattr(gnugrid.GNUGridClient, "credit_report", real)
    second = client.post("/api/v1/me/crb/check", headers=j.customer_headers, json=body).json()
    assert second["status"] == "VERIFIED" and second["report"]["numeric_score"] == 780
    assert len(gnugrid.MOCK_BUREAU.enquiries) == 1 and second["check_id"] == first["check_id"]
    with session_scope() as db:  # identity was recorded once, when the enquiry ran; the resume only adds the report
        ics = db.execute(select(IdentityCheck).where(IdentityCheck.customer_id == _cid(j),
                                                     IdentityCheck.provider == "crb_mock")).scalars().all()
        assert len(ics) == 1
        assert "crb.score_band" in current_facts(db, _cid(j))


def test_an_interrupted_enquiry_is_never_resent(client, journey, crb_on):
    j = _selected(journey, "0772480017")
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    cid = _cid(j)
    with session_scope() as db:  # a crash after sending left the row REQUESTED
        db.add(CrbCheck(customer_id=cid, institution_id=_lakeside(), provider="mock", status="REQUESTED", attempts=1))
        db.flush()
        db.execute(CrbCheck.__table__.update().where(CrbCheck.customer_id == cid)
                   .values(created_at=utcnow() - timedelta(hours=1)))
    r = client.post("/api/v1/me/crb/check", headers=j.customer_headers,
                    json={"selected_institution_id": str(_lakeside()), "consent": True}).json()
    assert r["status"] == "UNRESOLVED" and gnugrid.MOCK_BUREAU.enquiries == []


def _advisory_locks() -> int:
    from sqlalchemy import text
    with session_scope() as db:
        return db.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")).scalar_one()


def test_no_lock_is_left_behind_whatever_the_outcome(client, journey, crb_on, monkeypatch):
    j = _selected(journey, "0772480018")
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    body = _check_body(client, j)
    for _ in range(4):  # same customer and lender again and again: never waits on a stranded lock
        assert client.post("/api/v1/me/crb/check", headers=j.customer_headers, json=body).status_code == 200
        assert _advisory_locks() == 0
    with session_scope() as db:
        db.execute(CrbCheck.__table__.delete().where(CrbCheck.customer_id == _cid(j)))
    body = _check_body(client, j)
    monkeypatch.setattr(get_settings(), "gngrid_use_mock", False)  # early return: real bureau not configured
    monkeypatch.setattr(get_settings(), "env", "production")
    r = client.post("/api/v1/me/crb/check", headers=j.customer_headers, json=body).json()
    assert r["reason"] == "NOT_CONFIGURED" and _advisory_locks() == 0


def test_each_lender_sees_only_the_report_pulled_with_its_consent():
    cid, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with session_scope() as db:
        for inst, score in ((a, 780), (b, 410)):
            db.add(CrbCheck(customer_id=cid, institution_id=inst, provider="mock", status="VERIFIED",
                            verified_at=utcnow(), summary={"crb_reference_id": f"R{score}", "numeric_score": score}))
    with session_scope() as db:
        assert crb_service.report_for_institution(db, cid, a)["numeric_score"] == 780
        assert crb_service.report_for_institution(db, cid, b)["numeric_score"] == 410
        assert crb_service.report_for_institution(db, cid, uuid.uuid4()) is None


def test_correcting_the_national_id_lifts_a_not_found_block(client, journey, crb_on):
    j = _agree(_selected(journey, "0772480008", nin="CM0772480008ZZ"))
    assert not j.cards("submitted")
    r = client.put("/api/v1/me/identity", headers=j.customer_headers, json={"nin": "CM0772480008AB"})
    assert r.status_code == 200, r.text
    opt = next(o for o in j.cards("options")[-1]["options"] if o["institution"] == "Lakeside Bank")
    j.send(action="select", value=opt["match_id"])  # back on the options after the refusal: choose again
    _agree(j)  # a new lender check is asked for and runs on the corrected number
    assert j.cards("submitted"), j.texts()
    assert [c.status for c in _checks(_cid(j))] == ["SUPERSEDED", "VERIFIED"]


def test_with_real_gnugrid_typing_a_nin_triggers_no_billed_call(journey, monkeypatch):
    """JIT: the capture-time registry check is skipped; identity comes with the CRB check at lender selection."""
    monkeypatch.setattr(get_settings(), "identity_provider", "gnugrid")
    j = _selected(journey, "0772480006", select_lender=False)
    with session_scope() as db:
        assert not db.execute(select(IdentityCheck).where(IdentityCheck.customer_id == _cid(j))).first()
    assert gnugrid.MOCK_BUREAU.enquiries == []


def test_no_network_guard_really_blocks():
    with pytest.raises(AssertionError, match="network call attempted"):
        httpx.Client().get("https://api.gnugridcrb.com/health")
