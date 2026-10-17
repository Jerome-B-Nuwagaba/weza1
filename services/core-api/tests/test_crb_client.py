"""GnuGrid CRB client (API v1.08) and the deterministic interpretation of its answers.

Everything is local: a fake bureau replaces httpx.post. No enquiry ever leaves the machine; all credentials and
identity values are FAKE."""

import logging

import httpx
import pytest

from weza.config import get_settings
from weza.domains.verification import gnugrid
from weza.domains.verification import service as idv

BASE = "https://crb.test.invalid/api"
SECRET = "FAKE_crb_secret_must_never_print"
NIN = "CM1234567890AB"


def individual(surname="OKELLO", f1="JOHN", f2="BOSCO", f3="KEN", dob="1993-03-31", pid=12965):
    return {"individual_id": pid, "image": "", "surname": surname, "forename1": f1, "forename2": f2, "forename3": f3,
            "gender": "Male", "marital_status": "Single (never married)", "date_of_birth": dob,
            "nationality": "Ugandan"}


def enquiry(status="SUCCESSFUL", formal=None, informal=None, envelope=False):
    e = {"id": "57ca4cd1-db40-4d37-bebf-92fd5dc7a7ab", "entity": "Individual", "timestamp": "2026-10-16 10:00:00",
         "reference": "DBFREEYXQLUWURF", "criteria": "identifier", "search_value": NIN,
         "identification_type": "Country ID Number", "status": status, "cost": 0}
    for name, people in (("formal", formal), ("informal", informal)):
        if people is not None:
            e[name] = {"matches": len(people), "sector": name, "individuals": people}
    body = {"message": "success", "status": 200, "count": 1, "enquiry": e}
    return {"status": "success", "data": body, "message": "", "code": 200} if envelope else body


class FakeBureau:
    def __init__(self):
        self.calls: list[dict] = []
        self.token_response = (200, {"token_type": "Bearer", "expires_in": 3600, "access_token": "FAKE_ACCESS_1"})
        self.responses: list = []  # queued enquiry responses: (status, json) | Exception
        self.default = (200, enquiry(formal=[individual()]))

    def __call__(self, url, json=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        req = httpx.Request("POST", url)
        if url.endswith("/v1/oauth/token"):
            code, body = self.token_response
            return httpx.Response(code, json=body, request=req)
        assert url == f"{BASE}/v1/kyc-enquiries/request/new", url
        nxt = self.responses.pop(0) if self.responses else self.default
        if isinstance(nxt, Exception):
            raise nxt
        code, body = nxt
        return httpx.Response(code, json=body, request=req) if isinstance(body, dict) else \
            httpx.Response(code, content=body, request=req)

    def enquiries(self):
        return [c for c in self.calls if c["url"].endswith("/request/new")]

    def tokens(self):
        return [c for c in self.calls if c["url"].endswith("/oauth/token")]


@pytest.fixture()
def crb(monkeypatch):
    s = get_settings()
    for k, v in {"crb_base_url": BASE + "/", "crb_client_id": "FAKE_crb_client", "crb_client_secret": SECRET,
                 "crb_enquiry_reason": "Identity verification for a financing request (test)",
                 "crb_pi_code": "PI001"}.items():
        monkeypatch.setattr(s, k, v)
    fake = FakeBureau()
    monkeypatch.setattr(httpx, "post", fake)
    gnugrid._tokens.clear()
    yield fake
    gnugrid._tokens.clear()


# ------------------------------------------------------------------ request contract


def test_request_follows_the_specification(crb):
    res = gnugrid.kyc_enquiry_individual(NIN, "ii_country_id")
    assert res.ok and res.enquiry_id and res.reference == "DBFREEYXQLUWURF" and res.bureau_status == "SUCCESSFUL"
    (tok,) = crb.tokens()
    assert tok["url"] == f"{BASE}/v1/oauth/token"
    assert tok["json"] == {"grant_type": "client_credentials", "client_id": "FAKE_crb_client", "client_secret": SECRET}
    (enq,) = crb.enquiries()
    assert enq["headers"]["Authorization"] == "Bearer FAKE_ACCESS_1"
    assert enq["headers"]["Content-Type"] == "application/json" and enq["headers"]["Accept"] == "application/json"
    assert enq["json"] == {"identifier": NIN, "entity_type": 0, "identification_type": "ii_country_id",
                           "reason": "Identity verification for a financing request (test)",
                           "client_consented": "Yes", "pi_code": "PI001"}
    assert res.matches == {"formal": 1}
    (p,) = res.individuals
    assert (p.surname, p.forenames, p.date_of_birth) == ("OKELLO", ["JOHN", "BOSCO", "KEN"], "1993-03-31")


def test_pi_code_is_omitted_when_not_configured(crb, monkeypatch):
    monkeypatch.setattr(get_settings(), "crb_pi_code", "REPLACE_ME")
    gnugrid.kyc_enquiry_individual(NIN, "ii_country_id")
    assert "pi_code" not in crb.enquiries()[0]["json"]


def test_token_is_reused_until_expiry(crb):
    gnugrid.kyc_enquiry_individual(NIN, "ii_country_id")
    gnugrid.kyc_enquiry_individual(NIN, "ii_country_id")
    assert len(crb.tokens()) == 1 and len(crb.enquiries()) == 2


def test_expired_token_is_refreshed_once(crb):
    crb.responses = [(401, {"status": "error", "data": None, "message": "Unauthenticated.", "code": 401})]
    res = gnugrid.kyc_enquiry_individual(NIN, "ii_country_id")
    assert res.ok and len(crb.tokens()) == 2 and len(crb.enquiries()) == 2


def test_bad_client_credentials_are_an_auth_failure_and_no_enquiry_is_sent(crb):
    crb.token_response = (401, {"error": "invalid_client", "error_description": "Client authentication failed",
                                "message": "Client authentication failed"})
    res = gnugrid.kyc_enquiry_individual(NIN, "ii_country_id")
    assert res.category == gnugrid.AUTH and crb.enquiries() == []


# ------------------------------------------------------------------ failures


@pytest.mark.parametrize("code,body,category", [
    (402, {"subscription": "INSUFFICIENT ", "message": "Your institution account has insufficient funds for "
                                                       "Individual Credit Enquiries"}, gnugrid.BILLING),
    (403, {"subscription": "EXPIRED", "message": "subscription expired"}, gnugrid.BILLING),
    (403, {"status": "error", "data": None, "message": "Forbidden", "code": 403}, gnugrid.AUTH),
    (400, {"status": "error", "data": None, "message": "The identifier field is required.", "code": 400},
     gnugrid.INVALID_IDENTIFIER),
    (400, {"status": "error", "data": None, "message": "The reason field is required.", "code": 400}, gnugrid.INVALID),
    (429, {"message": "Too Many Attempts."}, gnugrid.UNAVAILABLE),
    (500, {"status": "error", "data": None, "message": "Server error", "code": 500}, gnugrid.UNAVAILABLE),
    (503, {"status": "error", "data": None, "message": "Unavailable", "code": 503}, gnugrid.UNAVAILABLE),
    (404, {"data": None, "message": "Route not found", "status": 404}, gnugrid.PROTOCOL),
    (200, {"message": "success", "status": 200}, gnugrid.PROTOCOL),  # 2xx without an enquiry
    (200, b"<html>not json</html>", gnugrid.PROTOCOL),
])
def test_failure_classification(crb, code, body, category):
    crb.responses = [(code, body)]
    res = gnugrid.kyc_enquiry_individual(NIN, "ii_country_id")
    assert res.category == category and not res.ok
    if category == gnugrid.BILLING:
        assert res.billing_state in gnugrid.BILLING_STATES


def test_connection_failure_is_retried_once_because_nothing_was_sent(crb):
    crb.responses = [httpx.ConnectError("refused")]
    assert gnugrid.kyc_enquiry_individual(NIN, "ii_country_id").ok
    assert len(crb.enquiries()) == 2
    crb.calls.clear()
    crb.responses = [httpx.ConnectError("refused"), httpx.ConnectTimeout("slow connect")]
    assert gnugrid.kyc_enquiry_individual(NIN, "ii_country_id").category == gnugrid.UNAVAILABLE
    assert len(crb.enquiries()) == 2


def test_timeout_after_sending_is_uncertain_and_never_resent(crb):
    crb.responses = [httpx.ReadTimeout("no answer")]
    assert gnugrid.kyc_enquiry_individual(NIN, "ii_country_id").category == gnugrid.UNCERTAIN
    assert len(crb.enquiries()) == 1  # may have been processed and charged


def test_spec_general_envelope_is_tolerated(crb):
    crb.responses = [(200, enquiry(formal=[individual()], envelope=True))]
    assert gnugrid.kyc_enquiry_individual(NIN, "ii_country_id").ok


def test_logs_carry_no_identifier_names_or_secrets(crb, caplog):
    crb.responses = [(503, {"message": "down"})]
    with caplog.at_level(logging.DEBUG):
        gnugrid.kyc_enquiry_individual(NIN, "ii_country_id")
        gnugrid.kyc_enquiry_individual(NIN, "ii_country_id")
    blob = " ".join(r.getMessage() + str(getattr(r, "data", "")) for r in caplog.records)
    assert NIN not in blob and "OKELLO" not in blob and SECRET not in blob and "FAKE_ACCESS_1" not in blob


# ------------------------------------------------------------------ interpretation (pure)


def result(**kw):
    crb_resp = enquiry(**kw)
    e = crb_resp["enquiry"]
    res = gnugrid.EnquiryResult(gnugrid.OK, 200, enquiry_id=e["id"], bureau_status=e["status"])
    for sector in ("formal", "informal"):
        if sector in e:
            res.matches[sector] = e[sector]["matches"]
            res.individuals += [gnugrid.CrbIndividual(sector, str(p["individual_id"]), p["surname"],
                                                      [p[k] for k in ("forename1", "forename2", "forename3") if p[k]],
                                                      p["date_of_birth"]) for p in e[sector]["individuals"]]
    return res


@pytest.mark.parametrize("claimed_name,claimed_dob,outcome,fields", [
    ("John Okello", "1993-03-31", "VERIFIED", {"name": "MATCH", "date_of_birth": "MATCH"}),
    ("okello  john-bosco", "1993-03-31", "VERIFIED", {"name": "MATCH", "date_of_birth": "MATCH"}),
    ("Ókello Ken", "1993-03-31", "VERIFIED", {"name": "MATCH", "date_of_birth": "MATCH"}),
    ("John Bosco", "1993-03-31", "DISCREPANCY", {"name": "MISMATCH", "date_of_birth": "MATCH"}),  # no surname
    ("Peter Okello", "1993-03-31", "DISCREPANCY", {"name": "MISMATCH", "date_of_birth": "MATCH"}),  # no forename
    ("John Okello", "1993-04-01", "DISCREPANCY", {"name": "MATCH", "date_of_birth": "MISMATCH"}),
])
def test_matching_rule(claimed_name, claimed_dob, outcome, fields):
    assert idv.interpret(result(formal=[individual()]), claimed_name, claimed_dob) == (outcome, fields)


def test_no_record_ambiguous_and_conflicting_profiles():
    assert idv.interpret(result(formal=[]), "John Okello", "1993-03-31")[0] == "NO_RECORD"
    two = result(formal=[individual(), individual(surname="OTIM", pid=2)])
    assert idv.interpret(two, "John Okello", "1993-03-31")[0] == "AMBIGUOUS"
    differ = result(formal=[individual()], informal=[individual(dob="1990-01-01", pid=1345)])
    assert idv.interpret(differ, "John Okello", "1993-03-31")[0] == "AMBIGUOUS"
    same = result(formal=[individual()], informal=[individual(pid=1345)])
    assert idv.interpret(same, "John Okello", "1993-03-31")[0] == "VERIFIED"


def test_missing_bureau_date_of_birth_is_never_verified():
    out, fields = idv.interpret(result(formal=[individual(dob="")]), "John Okello", "1993-03-31")
    assert out == "INCONCLUSIVE" and fields["date_of_birth"] == "NOT_CHECKED"


@pytest.mark.parametrize("status,outcome", [("PENDING", "PENDING"), ("INCOMPLETE", "PENDING"),
                                            ("FAILED", "UNAVAILABLE"), ("WEIRD", "UNAVAILABLE")])
def test_unfinished_bureau_status_is_never_verified(status, outcome):
    assert idv.interpret(result(status=status, formal=[individual()]), "John Okello", "1993-03-31")[0] == outcome


@pytest.mark.parametrize("category,outcome", [
    (gnugrid.AUTH, "CONFIG_ERROR"), (gnugrid.BILLING, "CONFIG_ERROR"), (gnugrid.INVALID, "CONFIG_ERROR"),
    (gnugrid.PROTOCOL, "CONFIG_ERROR"), (gnugrid.UNAVAILABLE, "UNAVAILABLE"), (gnugrid.UNCERTAIN, "UNCERTAIN"),
    (gnugrid.INVALID_IDENTIFIER, "INVALID_IDENTIFIER")])
def test_failures_are_never_verified(category, outcome):
    assert idv.interpret(gnugrid.EnquiryResult(category), "John Okello", "1993-03-31")[0] == outcome
