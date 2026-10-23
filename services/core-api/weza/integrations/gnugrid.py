"""gnuGRID CRB client — GnuGrid Enquiries API v1.08 (the only code that talks to the credit bureau).

Contract (docs/CRB_VERIFICATION.md §3 and the GnuGrid "ENQUIRIES API SPECIFICATION v1.08"):
  POST {base}/v1/oauth/token                               grant_type=client_credentials, client_id, client_secret
                                                           -> {token_type: "Bearer", expires_in, access_token}
  POST {base}/v1/credit-enquiries/request/new              identifier, entity_type (0 = individual),
                                                           identification_type, reason, client_consented ("Yes"),
                                                           pi_code (aggregators only)
                                                           -> enquiry {id, reference, status, cost,
                                                              formal/informal {matches, individuals[...]}}
  POST {base}/v1/credit-enquiries/individual/credit-report enquiry_id, individual_id, format ("json")
                                                           -> credit_information {scoring_details,
                                                              credit_accounts_summary, ...}
  Errors: {status: "error", message, code} 400/401/403/404/405/500/503; billing {subscription, message}.

There is no consent-code method (removed in v1.05): WEZA records the applicant's consent itself and sends
client_consented = "Yes". There is no idempotency key and every SUCCESSFUL enquiry is charged, so an enquiry is
retried automatically only when it certainly never reached the bureau (connection refused / connect timeout); a
timeout after sending raises CRBUncertain and is never resubmitted. Nothing here logs identifiers, names, tokens or
secrets, and the raw credit report (photo, contacts, addresses) is reduced to a summary and never kept.

- GNUGridClient: the real web service. Fill in GNUGRID_BASE_URL / GNUGRID_CLIENT_ID / GNUGRID_CLIENT_SECRET /
  GNUGRID_ENQUIRY_REASON (and GNUGRID_PI_CODE for an aggregator) and set GNGRID_USE_MOCK=false.
- MockGNUGridClient: the same client and parser over an offline bureau that answers with spec-shaped JSON
  (dev, staging, CI, demos). Production refuses it.
"""

import asyncio
import logging
import re
import threading
import time
import unicodedata
import uuid
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation

import httpx

from weza.config import get_settings, is_configured
from weza.schemas.crb import CrbEnquiry, CrbProfile, CRBSummaryReport

log = logging.getLogger("weza.crb")

ENTITY_INDIVIDUAL = 0
NIN = "ii_country_id"  # spec appendix: Country ID Number (NIN)
BILLING_STATES = {"NONE", "INSUFFICIENT", "EXPIRED", "CANCELLED"}
_RATING_BANDS = {"excellent": "EXCELLENT", "very good": "GOOD", "good": "GOOD", "fair": "FAIR", "average": "FAIR",
                 "moderate": "FAIR", "poor": "POOR", "very poor": "POOR", "bad": "POOR"}
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class CRBError(Exception):
    def __init__(self, category: str, message: str = "", http_status: int | None = None,
                 billing_state: str | None = None):
        super().__init__(f"{category}: {message}"[:300])
        self.category, self.message, self.http_status, self.billing_state = category, message, http_status, billing_state


class CRBUnavailable(CRBError):
    """Not processed by the bureau (unreachable, 5xx, 429, FAILED). Safe to try again later; never counts as verified."""


class CRBUncertain(CRBError):
    """Sent, but no usable answer: it may have been processed and charged. Never resubmitted automatically."""


class CRBConfigError(CRBError):
    """Credentials, subscription/float, request validation or an unreadable response: needs operations, not a retry."""


# ------------------------------------------------------------------ helpers


def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _int(v) -> int | None:
    try:
        return int(Decimal(str(v).replace(",", "").strip()))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(v) -> Decimal:
    try:
        return Decimal(str(v).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def _merged(items) -> dict:
    """The spec's summaries are lists of single-purpose dicts ([{Total_...}, {Credit_Accounts: [...]}]): merge by key."""
    out: dict = {}
    for it in items if isinstance(items, list) else [items] if isinstance(items, dict) else []:
        if isinstance(it, dict):
            out.update(it)
    return out


def _classify_error(r: httpx.Response, data: dict) -> CRBError:
    msg = str(data.get("message") or data.get("error_description") or data.get("error") or "")[:200]
    sub = str(data.get("subscription") or "").strip().upper()
    if sub in BILLING_STATES:
        return CRBConfigError("BILLING", msg, r.status_code, billing_state=sub)
    if r.status_code in (401, 403):
        return CRBConfigError("AUTH", msg, r.status_code)
    if r.status_code == 400:
        return CRBConfigError("INVALID_IDENTIFIER" if "identifier" in msg.lower() else "INVALID", msg, 400)
    if r.status_code == 429 or r.status_code >= 500:
        return CRBUnavailable("UNAVAILABLE", msg, r.status_code)
    return CRBConfigError("PROTOCOL", msg or f"HTTP {r.status_code}", r.status_code)


def parse_enquiry(data: dict) -> CrbEnquiry:
    enquiry = data.get("enquiry")
    if not isinstance(enquiry, dict) and isinstance(data.get("data"), dict):
        enquiry = data["data"].get("enquiry")  # tolerate the spec's general {data: {...}} envelope
    if not isinstance(enquiry, dict) or not enquiry.get("id"):
        raise CRBConfigError("PROTOCOL", "no enquiry in the response")
    cost = enquiry.get("cost")
    out = CrbEnquiry(enquiry_id=str(enquiry["id"])[:64], reference=str(enquiry.get("reference") or "")[:64] or None,
                     bureau_status=str(enquiry.get("status") or "").strip().upper()[:16] or None,
                     cost=float(_money(cost)) if cost is not None else None)
    for sector in ("formal", "informal"):
        block = enquiry.get(sector)
        if not isinstance(block, dict):
            continue
        out.matches[sector] = _int(block.get("matches")) or 0
        for p in block.get("individuals") or []:
            if isinstance(p, dict):
                out.profiles.append(CrbProfile(
                    sector=sector, individual_id=str(p["individual_id"]) if p.get("individual_id") else None,
                    surname=str(p.get("surname") or "").strip(),
                    forenames=[str(p[k]).strip() for k in ("forename1", "forename2", "forename3")
                               if p.get(k) and str(p[k]).strip()],
                    date_of_birth=str(p.get("date_of_birth") or "").strip()[:10] or None))
    return out


def phone_on_record(details, phone: str | None) -> bool | None:
    """Is `phone` among the contact numbers of the bureau record? None when there is no number to compare. Numbers
    are compared on their last 9 digits (a Ugandan mobile without 0 / +256); the record's numbers are never kept."""
    if not phone:
        return None
    found: list[str] = []

    def walk(v, contact: bool) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, contact or any(w in str(k).lower() for w in ("contact", "phone", "mobile", "tel")))
        elif isinstance(v, list):
            for x in v:
                walk(x, contact)
        elif contact and v is not None:
            found.extend(re.sub(r"\D", "", m)[-9:] for m in re.findall(r"\+?\d[\d\s-]{7,16}\d", str(v)))
    walk(details, False)
    if not found:
        return None
    return re.sub(r"\D", "", phone)[-9:] in found


def parse_report(data: dict, reference: str, phone: str | None = None) -> CRBSummaryReport:
    """Reduce the JSON credit report to the summary WEZA keeps. The raw report is never stored or logged."""
    ci = data.get("credit_information")
    if not isinstance(ci, dict) and isinstance(data.get("data"), dict):
        ci = data["data"].get("credit_information")
    if not isinstance(ci, dict):
        raise CRBConfigError("PROTOCOL", "no credit_information in the report")
    scoring = ci.get("scoring_details") if isinstance(ci.get("scoring_details"), dict) else {}
    accounts = _merged(ci.get("credit_accounts_summary"))
    ugx = [a for a in accounts.get("Credit_Accounts") or []
           if isinstance(a, dict) and str(a.get("Currency") or "UGX").upper() == "UGX"]
    outstanding = sum((_money(a.get("Loan_Balance")) for a in ugx), Decimal(0))
    overdue = sum((_money(a.get("Amount_Overdue")) for a in ugx), Decimal(0))
    adverse = _int(accounts.get("Adverse_Accounts")) or 0
    rating = re.sub(r"\s+", " ", str(scoring.get("Current_Score_Rating") or "").strip().lower())
    return CRBSummaryReport(
        crb_reference_id=reference, credit_score_band=_RATING_BANDS.get(rating),
        score_grade=(str(scoring.get("Current_Score_Band") or "").strip()[:8] or None),
        numeric_score=_int(scoring.get("Current_Score")),
        probability_of_default=(str(scoring.get("Probability_of_Default") or "").strip()[:12] or None),
        active_loans_count=_int(accounts.get("Open_Accounts")) or 0, adverse_accounts=adverse,
        worst_days_in_arrears=_int(accounts.get("Worst_Days_in_Arreas", accounts.get("Worst_Days_in_Arrears"))),
        has_active_defaults=adverse > 0 or overdue > 0, total_outstanding_balance_ugx=float(outstanding),
        phone_on_record=phone_on_record(ci.get("customer_details"), phone))


# ------------------------------------------------------------------ token cache


class _TokenCache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.tokens: dict[tuple[str, str], tuple[str, float]] = {}

    def clear(self) -> None:
        with self.lock:
            self.tokens.clear()


_tokens = _TokenCache()


# ------------------------------------------------------------------ client


class AbstractGNUGridClient(ABC):
    @abstractmethod
    def credit_enquiry(self, identifier: str, **kwargs) -> CrbEnquiry:
        """Create a chargeable enquiry after the service has verified lender-bound consent."""

    @abstractmethod
    def credit_report(self, enquiry_id: str, individual_id: str, *, reference: str,
                      phone: str | None = None) -> CRBSummaryReport:
        """Reduce an existing enquiry to a non-identifying credit summary (`phone`: checked against the record)."""


class GNUGridClient(AbstractGNUGridClient):
    name = "gnugrid"

    def __init__(self, post=None):
        s = get_settings()
        if not getattr(self, "_offline", False) and s.crb_missing:
            raise CRBConfigError("CONFIG", "gnuGRID not configured: " + ", ".join(s.crb_missing))
        self.base = (s.gnugrid_base_url or "https://mock.gnugrid.invalid").strip().rstrip("/")
        self.client_id, self.secret = (s.gnugrid_client_id or "mock").strip(), (s.gnugrid_client_secret or "").strip()
        self.reason, self.timeout = (s.gnugrid_enquiry_reason or "").strip(), s.gnugrid_timeout_seconds
        self.pi_code = s.gnugrid_pi_code.strip() if is_configured(s.gnugrid_pi_code) else None
        self._post_fn = post

    def _post(self, url: str, body: dict, headers: dict) -> httpx.Response:
        if not self._post_fn and not get_settings().is_production:
            raise CRBConfigError("CONFIG", "Live gnuGRID calls are permitted only in production")
        return (self._post_fn or httpx.post)(url, json=body, headers=headers, timeout=self.timeout)

    @staticmethod
    def _headers(token: str | None = None) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def token(self, *, refresh: bool = False) -> str:
        """A cached bearer token (refreshed 60 s before expiry). Free: no enquiry is made."""
        key = (self.base, self.client_id)
        with _tokens.lock:
            cached = _tokens.tokens.get(key)
            if cached and not refresh and time.monotonic() < cached[1]:
                return cached[0]
            try:
                r = self._post(f"{self.base}/v1/oauth/token", {"grant_type": "client_credentials",
                                                               "client_id": self.client_id,
                                                               "client_secret": self.secret}, self._headers())
            except httpx.HTTPError as exc:
                raise CRBUnavailable("UNAVAILABLE", "token request failed (network)") from exc
            data = _json(r)
            tok = data.get("access_token")
            if r.status_code < 300 and isinstance(tok, str) and tok:
                ttl = max(60, _int(data.get("expires_in")) or 300)
                _tokens.tokens[key] = (tok, time.monotonic() + ttl - 60)
                return tok
            if r.status_code >= 500:
                raise CRBUnavailable("UNAVAILABLE", "token endpoint unavailable", r.status_code)
            raise CRBConfigError("AUTH", str(data.get("error_description") or data.get("message")
                                             or data.get("error") or "authentication failed")[:200], r.status_code)

    def _call(self, path: str, body: dict, *, chargeable: bool) -> dict:
        url, refreshed, retried = f"{self.base}{path}", False, False
        while True:
            token = self.token(refresh=refreshed)
            try:
                r = self._post(url, body, self._headers(token))
            except _NOT_SENT as exc:
                if not retried:  # never reached the bureau: one immediate retry is safe
                    retried = True
                    continue
                raise CRBUnavailable("UNAVAILABLE", "bureau unreachable") from exc
            except httpx.HTTPError as exc:
                if chargeable:
                    raise CRBUncertain("UNCERTAIN", "no response after sending (may have been processed)") from exc
                raise CRBUnavailable("UNAVAILABLE", type(exc).__name__) from exc
            if r.status_code == 401 and not refreshed:  # token expired early: refresh once (request not processed)
                refreshed = True
                continue
            data = _json(r)
            if r.status_code >= 300 or str(data.get("subscription") or "").strip().upper() in BILLING_STATES:
                raise _classify_error(r, data)
            return data

    def credit_enquiry(self, identifier: str, *, identification_type: str = NIN, pi_code: str | None = None,
                       claimed_name: str | None = None) -> CrbEnquiry:
        """One CreditEnquiry for an individual. The caller must already hold the applicant's recorded consent.
        `claimed_name` is used only by the offline mock to simulate a matching record; it is never sent."""
        body = {"identifier": identifier.strip(), "entity_type": ENTITY_INDIVIDUAL,
                "identification_type": identification_type, "reason": self.reason, "client_consented": "Yes"}
        if pi_code or self.pi_code:
            body["pi_code"] = pi_code or self.pi_code
        try:
            enquiry = parse_enquiry(self._call("/v1/credit-enquiries/request/new", body, chargeable=True))
        except CRBConfigError as exc:
            if exc.category == "PROTOCOL" and not exc.http_status:
                # A 2xx we can't read may still have been charged: never resend it automatically
                raise CRBUncertain("UNCERTAIN", exc.message) from exc
            raise
        log.info("crb_credit_enquiry", extra={"data": {"provider": self.name, "bureau_status": enquiry.bureau_status,
                                                        "matches": enquiry.matches}})
        return enquiry

    def credit_report(self, enquiry_id: str, individual_id: str, *, reference: str,
                      phone: str | None = None) -> CRBSummaryReport:
        """CreditReport (format=json) for a profile returned by the enquiry, reduced to a summary."""
        data = self._call("/v1/credit-enquiries/individual/credit-report",
                          {"enquiry_id": enquiry_id, "individual_id": _int(individual_id) or individual_id,
                           "format": "json"}, chargeable=False)
        return parse_report(data, reference, phone)


# ------------------------------------------------------------------ offline bureau (spec-shaped JSON)


class _Resp:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, status: int, data: dict):
        self.status_code, self._data = status, data

    def json(self) -> dict:
        return self._data


MOCK_RECORD_PHONE = "0772 123 456"  # the offline bureau's contact number for every record


class MockBureau:
    """Answers like GnuGrid, offline. Scenario by NIN suffix:
    ZZ no record · MM two matching people · PP enquiry PENDING · BB no float (billing) · DD adverse accounts/arrears.
    Otherwise one match; its name echoes the applicant's (a name containing "Mismatch" returns someone else)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []  # (path, body) — lets tests count billable enquiries
        self._enquiries: dict[str, str] = {}  # enquiry id -> NIN

    @property
    def enquiries(self) -> list[dict]:
        return [b for p, b in self.calls if p.endswith("/credit-enquiries/request/new")]

    @staticmethod
    def _person(pid: int, name: str) -> dict:
        parts = [p for p in re.split(r"\s+", name.upper().strip()) if p] or ["OKELLO", "JOHN"]
        surname, fore = (parts[-1], parts[:-1]) if len(parts) > 1 else (parts[0], ["JOHN"])
        return {"individual_id": pid, "image": "", "surname": surname,
                **{f"forename{i + 1}": f for i, f in enumerate(fore[:3])}, "gender": "", "date_of_birth": None,
                "nationality": "Ugandan"}

    def __call__(self, url: str, json: dict, headers: dict, timeout: float):  # noqa: A002 — mirrors httpx.post
        path = url.split(".invalid", 1)[-1] if ".invalid" in url else "/" + url.split("/", 3)[-1]
        self.calls.append((path, dict(json)))
        if path.endswith("/oauth/token"):
            return _Resp(200, {"token_type": "Bearer", "expires_in": 3600, "access_token": "mock-token"})
        if path.endswith("/credit-enquiries/request/new"):
            nin = str(json.get("identifier") or "").upper()
            if json.get("client_consented") != "Yes":
                return _Resp(400, {"status": "error", "data": None, "message": "The client consented field is required.",
                                   "code": 400})
            if nin.endswith("BB"):
                return _Resp(403, {"subscription": "INSUFFICIENT",
                                   "message": "Your institution account has insufficient funds for Individual Credit "
                                              "Enquiries"})
            eid = str(uuid.uuid4())
            self._enquiries[eid] = nin
            claimed = str(json.get("_claimed_name") or "John Okello")
            name = "Okello John" if "mismatch" in claimed.lower() else claimed
            people = [] if nin.endswith("ZZ") else [self._person(12965, name)]
            if nin.endswith("MM"):
                people.append(self._person(12966, name))
            enquiry = {"id": eid, "entity": "Individual", "timestamp": "", "reference": f"MOCK{eid[:11].upper()}",
                       "criteria": "identifier", "search_value": "", "identification_type": "Country ID Number",
                       "status": "PENDING" if nin.endswith("PP") else "SUCCESSFUL", "cost": 0,
                       "formal": {"matches": len(people), "sector": "formal", "individuals": people}}
            return _Resp(200, {"message": "success", "status": 200, "count": 1, "enquiry": enquiry})
        if path.endswith("/credit-report"):
            nin = self._enquiries.get(str(json.get("enquiry_id")), "")
            if not nin:
                return _Resp(404, {"data": None, "message": "Enquiry not found", "status": 404})
            poor = nin.endswith("DD")
            info = {
                "scoring_details": {"Evaluation_Period": "", "Current_Score": 410 if poor else 780,
                                    "Current_Score_Band": "CC" if poor else "AAA",
                                    "Current_Score_Rating": "Poor" if poor else "Excellent",
                                    "Probability_of_Default": "38.50%" if poor else "4.10%"},
                "credit_accounts_summary": [
                    {"Total_Credit_Accounts": 3 if poor else 2, "Open_Accounts": 2 if poor else 1, "Closed_Accounts": 1,
                     "Adverse_Accounts": 1 if poor else 0, "Worst_Days_in_Arreas": 120 if poor else 0},
                    {"Credit_Accounts": [{"Currency": "UGX", "Loan_Amount": 9000000,
                                          "Loan_Balance": "6500000.00" if poor else "1200000.00",
                                          "Amount_Overdue": "850000.00" if poor else "0.00"}]}],
                "customer_details": {"Photo": "<never stored>", "Name": "", "Contact": MOCK_RECORD_PHONE}}
            return _Resp(200, {"message": "success", "status": 200, "count": 1, "credit_information": info})
        return _Resp(405, {"status": "error", "data": None, "message": "Method is not allowed for the requested route",
                           "code": 405})


MOCK_BUREAU = MockBureau()


class GNUGridHTTPClient(GNUGridClient):
    """Async HTTP transport adapted to the synchronous database service worker thread."""

    async def _post_async(self, url: str, body: dict, headers: dict) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            return await client.post(url, json=body, headers=headers)

    def _post(self, url: str, body: dict, headers: dict) -> httpx.Response:
        if self._post_fn:
            return self._post_fn(url, json=body, headers=headers, timeout=self.timeout)
        if not get_settings().is_production:
            raise CRBConfigError("CONFIG", "Live gnuGRID calls are permitted only in production")
        return asyncio.run(self._post_async(url, body, headers))


class MockGNUGridClient(GNUGridClient):
    """The real client and parser over the offline bureau. Free; makes no network calls."""

    name = "mock"
    _offline = True

    def __init__(self, bureau: MockBureau | None = None):
        super().__init__(post=bureau or MOCK_BUREAU)
        # Never share bearer token cache entries with a configured production endpoint.
        self.base, self.client_id, self.secret = "https://mock.gnugrid.invalid", "mock", ""
        self.simulate_defaults = False

    def credit_enquiry(self, identifier: str, *, identification_type: str = NIN, pi_code: str | None = None,
                       claimed_name: str | None = None) -> CrbEnquiry:
        real = self._post_fn

        def post(url, json, headers, timeout):  # noqa: A002
            return real(url, {**json, "_claimed_name": claimed_name or ""} if "request/new" in url else json,
                        headers, timeout)
        self._post_fn = post
        try:
            return super().credit_enquiry(identifier, identification_type=identification_type, pi_code=pi_code)
        finally:
            self._post_fn = real

    def credit_report(self, enquiry_id: str, individual_id: str, *, reference: str,
                      phone: str | None = None) -> CRBSummaryReport:
        report = super().credit_report(enquiry_id, individual_id, reference=reference, phone=phone)
        if self.simulate_defaults:
            return report.model_copy(update={"credit_score_band": "POOR", "numeric_score": 410,
                                              "has_active_defaults": True, "adverse_accounts": 1})
        return report


def get_crb_client() -> AbstractGNUGridClient:
    s = get_settings()
    return MockGNUGridClient() if s.gngrid_use_mock or not s.is_production else GNUGridHTTPClient()


def normalise_name(s: str | None) -> list[str]:
    t = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return [w for w in re.split(r"[^a-z]+", t) if w]
