"""gnuGRID CRB provider adapters (provider pattern).

- MockGNUGridClient: free and offline, for development, staging and CI (GNGRID_USE_MOCK=true). Makes no network calls.
- GNUGridHTTPClient: the real gnuGRID API. Request paths and the response mapping must be confirmed against gnuGRID's
  API documentation; until then anything that isn't exactly a CRBSummaryReport is treated as unavailable (fail
  closed), so nobody is ever reported as verified by mistake.

Clients are synchronous, like the rest of the core API (sync SQLAlchemy sessions, sync FastAPI routes) and the
existing identity adapter (weza/domains/verification/adapters.py)."""

import logging
import uuid
from abc import ABC, abstractmethod

import httpx
from pydantic import ValidationError

from weza.config import get_settings
from weza.schemas.crb import CRBConsentOTPChallenge, CRBConsentOTPVerify, CRBConsentRequest, CRBSummaryReport

log = logging.getLogger("weza.crb")


class CRBUnavailable(Exception):
    """The bureau couldn't be reached or gave an answer we can't interpret. Never counts as verified; retry later."""


class CRBOTPInvalid(Exception):
    """The applicant's consent code was wrong or has expired."""


def mask(phone: str) -> str:
    return f"{phone[:4]}•••••{phone[-3:]}" if len(phone) > 7 else "•••"


class AbstractGNUGridClient(ABC):
    name: str

    @abstractmethod
    def request_consent_otp(self, req: CRBConsentRequest) -> CRBConsentOTPChallenge:
        """Ask the bureau to send the applicant a consent code for this lender."""

    @abstractmethod
    def verify_otp_and_pull_summary(self, verify: CRBConsentOTPVerify) -> CRBSummaryReport:
        """Confirm the applicant's code and return their credit summary."""


class MockGNUGridClient(AbstractGNUGridClient):
    """Deterministic offline bureau.

    - OTP 000000: the applicant has an active default (POOR band, score 410).
    - Any other OTP: EXCELLENT, score 780, no defaults.
    - OTP 999999: wrong code (CRBOTPInvalid), to exercise retries.
    - NIN ending ZZ: not on the bureau (NOT_FOUND). Name containing "Mismatch" is checked by the identity layer, not here.
    """

    name = "mock"
    _sessions: dict[str, tuple[str, str]] = {}  # session_id -> (challenge_id, national_id); process-local is enough

    def request_consent_otp(self, req: CRBConsentRequest) -> CRBConsentOTPChallenge:
        session_id, challenge_id = f"MOCK-SESS-{uuid.uuid4().hex[:12]}", f"MOCK-CH-{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = (challenge_id, req.national_id.strip().upper())
        return CRBConsentOTPChallenge(session_id=session_id, challenge_id=challenge_id,
                                      masked_phone=mask(req.phone_number))

    def verify_otp_and_pull_summary(self, verify: CRBConsentOTPVerify) -> CRBSummaryReport:
        challenge, nin = self._sessions.get(verify.session_id, (None, ""))
        if challenge != verify.challenge_id or verify.otp_code.strip() == "999999":
            raise CRBOTPInvalid("code not accepted")
        ref = f"MOCK-CRB-{verify.session_id[-6:]}"
        if nin.endswith("ZZ"):
            return CRBSummaryReport(crb_reference_id=ref, verification_status="NOT_FOUND", credit_score_band=None,
                                    numeric_score=None, active_loans_count=0, has_active_defaults=False,
                                    total_outstanding_balance_ugx=0)
        if verify.otp_code.strip() == "000000":
            return CRBSummaryReport(crb_reference_id=ref, verification_status="VERIFIED", credit_score_band="POOR",
                                    numeric_score=410, active_loans_count=2, has_active_defaults=True,
                                    total_outstanding_balance_ugx=6_500_000)
        return CRBSummaryReport(crb_reference_id=ref, verification_status="VERIFIED", credit_score_band="EXCELLENT",
                                numeric_score=780, active_loans_count=1, has_active_defaults=False,
                                total_outstanding_balance_ugx=1_200_000)


class GNUGridHTTPClient(AbstractGNUGridClient):
    name = "gnugrid"

    def __init__(self):
        s = get_settings()
        if not (s.gnugrid_base_url and s.gnugrid_api_key):
            raise CRBUnavailable("gnuGRID not configured")
        self.base, self.key, self.timeout = s.gnugrid_base_url.rstrip("/"), s.gnugrid_api_key, s.gnugrid_timeout_seconds
        self.otp_path, self.verify_path = s.gnugrid_crb_otp_path, s.gnugrid_crb_verify_path

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(f"{self.base}/{path.lstrip('/')}", json=payload,
                           headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json"})
        except httpx.HTTPError as exc:
            log.warning("crb_unreachable", extra={"data": {"provider": self.name}})
            raise CRBUnavailable(type(exc).__name__) from exc
        if r.status_code >= 500:
            raise CRBUnavailable(f"HTTP {r.status_code}")
        try:
            return r.status_code, r.json()
        except ValueError as exc:
            raise CRBUnavailable("non-JSON response") from exc

    def request_consent_otp(self, req: CRBConsentRequest) -> CRBConsentOTPChallenge:
        status, body = self._post(self.otp_path, {"national_id": req.national_id, "phone_number": req.phone_number,
                                                  "reference": str(req.selected_institution_id)})
        if status >= 400:
            raise CRBUnavailable(f"HTTP {status}")
        try:
            return CRBConsentOTPChallenge.model_validate(body)
        except ValidationError as exc:
            raise CRBUnavailable("unrecognised OTP response — confirm the mapping with gnuGRID's docs") from exc

    def verify_otp_and_pull_summary(self, verify: CRBConsentOTPVerify) -> CRBSummaryReport:
        status, body = self._post(self.verify_path, {"session_id": verify.session_id,
                                                     "challenge_id": verify.challenge_id, "otp": verify.otp_code})
        if status in (400, 401, 403):
            raise CRBOTPInvalid(f"HTTP {status}")
        if status >= 400:
            raise CRBUnavailable(f"HTTP {status}")
        try:
            return CRBSummaryReport.model_validate(body)
        except ValidationError as exc:
            raise CRBUnavailable("unrecognised report — confirm the mapping with gnuGRID's docs") from exc


def get_crb_client() -> AbstractGNUGridClient:
    return MockGNUGridClient() if get_settings().gngrid_use_mock else GNUGridHTTPClient()
