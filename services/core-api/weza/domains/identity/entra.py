"""Microsoft Entra ID sign-in for staff (TSD §13: "institution users use enterprise authentication with MFA, preferably
Entra ID where supported").

Authorization-code flow with PKCE. WEZA never sees the user's Entra password. After Microsoft authenticates the user:
- the ID token is validated (signature against Microsoft's published keys, issuer, audience, expiry, nonce);
- the user must ALREADY exist in WEZA and be ACTIVE: Entra proves who they are, WEZA's own roles decide what they may do;
- the WEZA session is the same as a password login. It counts as MFA-verified only if Microsoft says MFA was performed
  (the `amr` claim contains "mfa"); otherwise the usual MFA rules still apply.

Single tenant only. Matching a user by the email in a token is safe only when the tenant is one we trust, so a
multi-tenant authority ("common", "organizations", "consumers") is refused rather than configured. Letting each
institution bring its own tenant needs a per-institution tenant id and is a later step.
"""

import base64
import hashlib
import json
import logging
import secrets
import time
import uuid
from urllib.parse import urlencode

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.identity import service as identity
from weza.domains.identity.models import User
from weza.domains.trust.service import audit
from weza.platform import crypto
from weza.platform.context import Actor
from weza.platform.controls import rate_limit
from weza.platform.errors import Forbidden, Unauthorized, ValidationFailed

log = logging.getLogger("weza.entra")
AUTHORITY = "https://login.microsoftonline.com"
_jwks: dict = {"at": 0.0, "keys": {}}
JWKS_TTL = 3600


def _is_guid(value: str | None) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def enabled() -> bool:
    """Configured, and for ONE tenant given by its GUID (Microsoft puts the GUID in every token's issuer, so the check is exact)."""
    s = get_settings()
    return bool(_is_guid(s.entra_tenant_id) and s.entra_client_id and s.entra_client_secret and s.entra_redirect_uri)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def safe_next(path: str | None) -> str | None:
    """Only a path inside this app (never another site), so the sign-in cannot be used as an open redirect."""
    return path if path and path.startswith("/") and not path.startswith("//") and chr(92) not in path else None


def begin(next_path: str | None = None) -> tuple[str, str]:
    """(URL to send the browser to, signed state). The state carries the nonce and the PKCE verifier; the caller also
    keeps it in a cookie, and the callback only proceeds when the two match (CSRF / login-fixation protection)."""
    if not enabled():
        raise ValidationFailed("Microsoft sign-in is not configured.", code="ENTRA_NOT_CONFIGURED")
    s = get_settings()
    nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    state = crypto.sign_jwt({"typ": "entra", "nonce": nonce, "cv": verifier, "next": safe_next(next_path)}, 10)
    query = urlencode({
        "client_id": s.entra_client_id, "response_type": "code", "redirect_uri": s.entra_redirect_uri,
        "response_mode": "query", "scope": "openid profile email", "state": state, "nonce": nonce,
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return f"{AUTHORITY}/{s.entra_tenant_id}/oauth2/v2.0/authorize?{query}", state


def _signing_key(kid: str):
    """The RSA public key Microsoft signed this token with, from its published key set (cached for an hour)."""
    s = get_settings()
    if kid not in _jwks["keys"] or time.monotonic() - _jwks["at"] > JWKS_TTL:
        r = httpx.get(f"{AUTHORITY}/{s.entra_tenant_id}/discovery/v2.0/keys", timeout=10)
        r.raise_for_status()
        _jwks["keys"] = {k["kid"]: k for k in r.json().get("keys", []) if k.get("kty") == "RSA"}
        _jwks["at"] = time.monotonic()
    if kid not in _jwks["keys"]:
        raise Unauthorized("Microsoft sign-in could not be verified.", code="ENTRA_KEY_UNKNOWN")
    return RSAAlgorithm.from_jwk(json.dumps(_jwks["keys"][kid]))


def _validate_id_token(id_token: str, nonce: str) -> dict:
    s = get_settings()
    try:
        kid = jwt.get_unverified_header(id_token).get("kid") or ""
        claims = jwt.decode(id_token, _signing_key(kid), algorithms=["RS256"], audience=s.entra_client_id,
                            issuer=f"{AUTHORITY}/{s.entra_tenant_id}/v2.0", options={"require": ["exp", "iat", "iss", "aud"]})
    except Unauthorized:
        raise
    except Exception as exc:  # noqa: BLE001 — any validation failure is the same answer to the browser
        log.warning("entra_token_rejected", extra={"data": {"err": type(exc).__name__}})
        raise Unauthorized("Microsoft sign-in could not be verified.", code="ENTRA_TOKEN_INVALID") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise Unauthorized("Microsoft sign-in could not be verified.", code="ENTRA_NONCE_MISMATCH")
    return claims


def complete(db: Session, code: str, state: str, cookie_state: str | None, ip: str = "") -> tuple[dict, str | None]:
    """Finish the sign-in. Returns the same result as a password login (tokens and user summary), and the page the
    user was heading for."""
    if not enabled():
        raise ValidationFailed("Microsoft sign-in is not configured.", code="ENTRA_NOT_CONFIGURED")
    if ip:
        rate_limit(db, f"entra:ip:{crypto.sha256_hex(ip)}", get_settings().login_ip_limit, 900)
    if not cookie_state or not secrets.compare_digest(state.encode(), cookie_state.encode()):
        raise Unauthorized("Your sign-in session expired. Please try again.", code="ENTRA_STATE_MISMATCH")
    try:
        claims = crypto.verify_jwt(state)
    except Exception as exc:  # noqa: BLE001
        raise Unauthorized("Your sign-in session expired. Please try again.", code="ENTRA_STATE_EXPIRED") from exc
    if claims.get("typ") != "entra":
        raise Unauthorized("Your sign-in session expired. Please try again.", code="ENTRA_STATE_MISMATCH")
    s = get_settings()
    try:
        r = httpx.post(f"{AUTHORITY}/{s.entra_tenant_id}/oauth2/v2.0/token", timeout=15, data={
            "client_id": s.entra_client_id, "client_secret": s.entra_client_secret, "grant_type": "authorization_code",
            "code": code, "redirect_uri": s.entra_redirect_uri, "code_verifier": claims["cv"]})
        body = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError) as exc:
        raise Unauthorized("Microsoft sign-in is unavailable. Please try again.", code="ENTRA_UNAVAILABLE") from exc
    if not body.get("id_token"):
        raise Unauthorized("Microsoft did not complete the sign-in.", code="ENTRA_CODE_REJECTED")
    token_claims = _validate_id_token(body["id_token"], claims["nonce"])
    email = str(token_claims.get("preferred_username") or token_claims.get("email") or token_claims.get("upn") or "").lower().strip()
    user = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none() if email else None
    if user is None or user.status != "ACTIVE":
        audit(db, Actor(kind="ANONYMOUS", display=email[:120] or "unknown", ip=ip[:64]), "auth.entra_denied", "user",
              user.id if user else "unknown", reason="no active WEZA account for this Microsoft identity")
        db.commit()  # the audit row must survive the error response's rollback
        raise Forbidden("Your Microsoft account is not set up in WEZA. Ask your administrator to add you.",
                        code="ENTRA_NO_ACCOUNT")
    mfa_done = "mfa" in (token_claims.get("amr") or [])
    user.failed_logins = 0
    audit(db, Actor(kind="ANONYMOUS", display=email[:120], ip=ip[:64]), "auth.entra_login", "user", user.id,
          after={"mfa": mfa_done})
    if not mfa_done and identity.mfa_required(user):
        # Microsoft did not perform MFA, so WEZA's own second factor still applies, exactly as for a password login.
        mfa_token = crypto.sign_jwt({"sub": str(user.id), "typ": "mfa", "token_version": user.token_version}, 10)
        pending = {"mfa_enrolment_required": True} if not user.mfa_enrolled else {"mfa_required": True}
        return {**pending, "mfa_token": mfa_token}, safe_next(claims.get("next"))
    return identity._issue_tokens(db, user, mfa=mfa_done), safe_next(claims.get("next"))
