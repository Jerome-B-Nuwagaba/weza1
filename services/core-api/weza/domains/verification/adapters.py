"""Identity-registry adapters. Each takes the applicant's NIN and name and returns a VerificationResult; none ever
raises — a transport problem is an ERROR result, retried by the outbox, and never counts as verified.

- simulator: deterministic, for demo/test environments (NIN ending ZZ → not found; name with "Mismatch" → mismatch).
- gnugrid:   the gnuGRID API. The request/response mapping is completed from gnuGRID's API documentation; until then
             it reports ERROR (fail closed) so nobody is marked verified by mistake."""

import logging
from dataclasses import dataclass

import httpx

from weza.config import get_settings

log = logging.getLogger("weza.verification")


@dataclass(frozen=True)
class VerificationResult:
    status: str  # VERIFIED | MISMATCH | NOT_FOUND | ERROR
    name_match: bool | None = None
    dob_match: bool | None = None
    provider_ref: str | None = None
    error: str | None = None


def _simulator(nin: str, full_name: str | None) -> VerificationResult:
    """Demo/test registry: a NIN ending in ZZ is unknown; a name containing 'Mismatch' doesn't match the registry."""
    n = (nin or "").strip().upper()
    if not n:
        return VerificationResult("ERROR", error="no NIN")
    if n.endswith("ZZ"):
        return VerificationResult("NOT_FOUND", provider_ref=f"SIM-{n[-6:]}")
    if full_name and "mismatch" in full_name.lower():
        return VerificationResult("MISMATCH", name_match=False, provider_ref=f"SIM-{n[-6:]}")
    return VerificationResult("VERIFIED", name_match=True if full_name else None, provider_ref=f"SIM-{n[-6:]}")


def _gnugrid(nin: str, full_name: str | None) -> VerificationResult:
    s = get_settings()
    if not (s.gnugrid_base_url and s.gnugrid_api_key):
        log.error("identity_provider_not_configured", extra={"data": {"provider": "gnugrid"}})
        return VerificationResult("ERROR", error="gnuGRID not configured")
    try:
        r = httpx.post(f"{s.gnugrid_base_url.rstrip('/')}/{s.gnugrid_verify_path.lstrip('/')}",
                       json={"nin": nin, "full_name": full_name},
                       headers={"Authorization": f"Bearer {s.gnugrid_api_key}", "Accept": "application/json"},
                       timeout=15)
    except httpx.HTTPError as exc:
        log.warning("identity_provider_unreachable", extra={"data": {"provider": "gnugrid"}})
        return VerificationResult("ERROR", error=type(exc).__name__)
    if r.status_code >= 500:
        return VerificationResult("ERROR", error=f"HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError:
        return VerificationResult("ERROR", error="non-JSON response")
    return map_gnugrid_response(r.status_code, body)


def map_gnugrid_response(status_code: int, body: dict) -> VerificationResult:
    """Translate gnuGRID's response into a VerificationResult.

    PENDING gnuGRID API DOCS: field names below are placeholders until the team receives the gnuGRID API
    specification. Anything not positively recognised as a match is NOT treated as verified."""
    if status_code == 404:
        return VerificationResult("NOT_FOUND")
    if status_code >= 400:
        return VerificationResult("ERROR", error=f"HTTP {status_code}")
    status = str(body.get("status") or "").upper()
    ref = body.get("reference") or body.get("request_id")
    name_match = body.get("name_match")
    if status in ("VERIFIED", "MATCH", "VALID") and name_match is not False:
        return VerificationResult("VERIFIED", name_match=name_match, provider_ref=ref)
    if status in ("NOT_FOUND", "INVALID", "UNKNOWN"):
        return VerificationResult("NOT_FOUND", provider_ref=ref)
    if status in ("MISMATCH", "NO_MATCH") or name_match is False:
        return VerificationResult("MISMATCH", name_match=name_match, provider_ref=ref)
    return VerificationResult("ERROR", provider_ref=ref, error=f"unrecognised status {status or '∅'}")


IDENTITY_PROVIDERS = {"simulator": _simulator, "gnugrid": _gnugrid}
