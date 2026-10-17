"""GnuGrid CRB Enquiries API v1.08 client (KYC enquiry only). The ONLY code that talks to the credit bureau.

Contract (from the supplied specification — do not extend without it):
  POST {base}/v1/oauth/token                  grant_type=client_credentials, client_id, client_secret
                                              → {token_type: "Bearer", expires_in, access_token}
  POST {base}/v1/kyc-enquiries/request/new    identifier, entity_type (0 = individual), identification_type,
                                              reason, client_consented ("Yes"), pi_code (optional, aggregators)
                                              → enquiry {id, reference, status, cost, formal/informal {matches,
                                                 individuals[surname, forename1..3, date_of_birth, ...]}}
  Errors: {status:"error", message, code} with 400/401/403/404/405/500/503; billing {subscription, message}.

The API has no idempotency key and charges every SUCCESSFUL enquiry, so an enquiry is retried automatically only when
it certainly never reached the bureau (connection refused / connect timeout). A timeout after sending is UNCERTAIN.
Nothing here logs identifiers, names, dates of birth, tokens or secrets.
"""

import logging
import threading
import time
from dataclasses import dataclass, field

import httpx

from weza.config import get_settings

log = logging.getLogger("weza.crb")

IDENTIFICATION_TYPES = {"NIN": "ii_country_id", "PASSPORT": "ii_passport_number"}  # spec appendix (subset used)
ENTITY_INDIVIDUAL = 0
BILLING_STATES = {"NONE", "INSUFFICIENT", "EXPIRED", "CANCELLED"}

# result categories
OK = "OK"
AUTH = "AUTH"  # bad client credentials / token rejected / forbidden
BILLING = "BILLING"  # subscription NONE / INSUFFICIENT / EXPIRED / CANCELLED
INVALID = "INVALID"  # 400 validation error
INVALID_IDENTIFIER = "INVALID_IDENTIFIER"  # 400 that names the identifier field
UNAVAILABLE = "UNAVAILABLE"  # request not processed (connect failure, 503, 5xx, 429) — safe to try again later
UNCERTAIN = "UNCERTAIN"  # may have been processed (and charged): never resubmitted automatically
PROTOCOL = "PROTOCOL"  # 2xx we cannot interpret, 404/405 on a documented route


@dataclass
class CrbIndividual:
    sector: str
    individual_id: str | None
    surname: str
    forenames: list[str]
    date_of_birth: str | None


@dataclass
class EnquiryResult:
    category: str
    http_status: int | None = None
    message: str = ""  # bureau message, for operators (never shown to customers)
    billing_state: str | None = None
    enquiry_id: str | None = None
    reference: str | None = None
    bureau_status: str | None = None  # PENDING / INCOMPLETE / SUCCESSFUL / FAILED
    cost: float | None = None
    matches: dict[str, int] = field(default_factory=dict)  # sector → matches
    individuals: list[CrbIndividual] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.category == OK


class _TokenCache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.token: str | None = None
        self.expires_at = 0.0

    def clear(self) -> None:
        with self.lock:
            self.token, self.expires_at = None, 0.0


_tokens = _TokenCache()
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def _base() -> str:
    return (get_settings().crb_base_url or "").strip().rstrip("/")


def _headers(token: str | None = None) -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _token() -> tuple[str | None, EnquiryResult | None]:
    """A cached bearer token (refreshed 60 s before expiry), or the failure."""
    s = get_settings()
    with _tokens.lock:
        if _tokens.token and time.monotonic() < _tokens.expires_at:
            return _tokens.token, None
        body = {"grant_type": "client_credentials", "client_id": (s.crb_client_id or "").strip(),
                "client_secret": (s.crb_client_secret or "").strip()}
        try:
            r = httpx.post(f"{_base()}/v1/oauth/token", json=body, headers=_headers(), timeout=s.crb_timeout_seconds)
        except httpx.HTTPError:
            return None, EnquiryResult(UNAVAILABLE, message="token request failed (network)")
        data = _json(r)
        tok = data.get("access_token")
        if r.status_code < 300 and isinstance(tok, str) and tok:
            try:
                ttl = max(60, int(data.get("expires_in") or 300))
            except (TypeError, ValueError):
                ttl = 300
            _tokens.token, _tokens.expires_at = tok, time.monotonic() + ttl - 60
            return tok, None
        if r.status_code >= 500:
            return None, EnquiryResult(UNAVAILABLE, r.status_code, "token endpoint unavailable")
        return None, EnquiryResult(AUTH, r.status_code, str(data.get("error_description") or data.get("message")
                                                            or data.get("error") or "authentication failed")[:200])


def _classify(r: httpx.Response) -> EnquiryResult:
    data = _json(r)
    msg = str(data.get("message") or "")[:200]
    sub = str(data.get("subscription") or "").strip().upper()
    if sub in BILLING_STATES:
        return EnquiryResult(BILLING, r.status_code, msg, billing_state=sub)
    if r.status_code in (401, 403):
        return EnquiryResult(AUTH, r.status_code, msg)
    if r.status_code == 400:
        return EnquiryResult(INVALID_IDENTIFIER if "identifier" in msg.lower() else INVALID, 400, msg)
    if r.status_code == 429 or r.status_code >= 500:
        return EnquiryResult(UNAVAILABLE, r.status_code, msg)
    if r.status_code >= 300:
        return EnquiryResult(PROTOCOL, r.status_code, msg)
    enquiry = data.get("enquiry")
    if not isinstance(enquiry, dict) and isinstance(data.get("data"), dict):
        enquiry = data["data"].get("enquiry")  # tolerate the spec's general {data: {...}} envelope
    if not isinstance(enquiry, dict) or not enquiry.get("id"):
        return EnquiryResult(PROTOCOL, r.status_code, msg or "no enquiry in response")
    res = EnquiryResult(OK, r.status_code, msg, enquiry_id=str(enquiry["id"])[:64],
                        reference=str(enquiry.get("reference") or "")[:64] or None,
                        bureau_status=str(enquiry.get("status") or "").strip().upper()[:16] or None)
    try:
        res.cost = float(enquiry["cost"]) if enquiry.get("cost") is not None else None
    except (TypeError, ValueError):
        res.cost = None
    for sector in ("formal", "informal"):
        block = enquiry.get(sector)
        if not isinstance(block, dict):
            continue
        try:
            res.matches[sector] = int(block.get("matches") or 0)
        except (TypeError, ValueError):
            res.matches[sector] = 0
        for p in block.get("individuals") or []:
            if isinstance(p, dict):
                res.individuals.append(CrbIndividual(
                    sector=sector, individual_id=str(p.get("individual_id")) if p.get("individual_id") else None,
                    surname=str(p.get("surname") or "").strip(),
                    forenames=[str(p.get(k)).strip() for k in ("forename1", "forename2", "forename3")
                               if p.get(k) and str(p.get(k)).strip()],
                    date_of_birth=str(p.get("date_of_birth") or "").strip()[:10] or None))
    return res


def kyc_enquiry_individual(identifier: str, identification_type: str) -> EnquiryResult:
    """Submit one KYC enquiry for an individual. The caller must already hold the customer's consent."""
    s = get_settings()
    body = {"identifier": identifier, "entity_type": ENTITY_INDIVIDUAL, "identification_type": identification_type,
            "reason": (s.crb_enquiry_reason or "").strip(), "client_consented": "Yes"}
    if (s.crb_pi_code or "").strip() and (s.crb_pi_code or "").strip().upper() != "REPLACE_ME":
        body["pi_code"] = s.crb_pi_code.strip()
    url = f"{_base()}/v1/kyc-enquiries/request/new"
    refreshed = sent_retry = False
    while True:
        token, failure = _token()
        if failure:
            return failure
        try:
            r = httpx.post(url, json=body, headers=_headers(token), timeout=s.crb_timeout_seconds)
        except _NOT_SENT:
            if not sent_retry:  # never reached the bureau: one immediate retry is safe
                sent_retry = True
                continue
            return EnquiryResult(UNAVAILABLE, message="bureau unreachable")
        except httpx.HTTPError:
            return EnquiryResult(UNCERTAIN, message="no response after sending (may have been processed)")
        if r.status_code == 401 and not refreshed:  # token expired early: refresh once (request was not processed)
            refreshed = True
            _tokens.clear()
            continue
        res = _classify(r)
        log.info("crb_kyc_enquiry", extra={"data": {"category": res.category, "http": res.http_status,
                                                     "bureau_status": res.bureau_status, "matches": res.matches}})
        return res
