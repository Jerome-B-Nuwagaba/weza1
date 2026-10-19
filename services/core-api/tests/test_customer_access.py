"""Browser handoff: one-time credentials, phone proof, cookie isolation and CSRF."""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from fastapi import Response
from sqlalchemy import select

from weza.config import get_settings
from weza.domains.customer import auth, service
from weza.domains.identity import service as identity
from weza.domains.identity.models import CustomerSession, OtpChallenge
from weza.platform import crypto
from weza.platform.db import session_scope, utcnow

CSRF = {"X-WEZA-CSRF": "1", "Origin": "http://localhost:3000"}


def magic(phone):
    with session_scope() as db:
        customer, _ = service.get_or_create_by_phone(db, phone)
        link = auth.issue_magic_link(db, customer.id)
        return parse_qs(urlparse(link).query)["token"][0], customer.id


def test_magic_handoff_is_single_use_and_cookie_opens_customer_screens(client):
    token, customer_id = magic("+256772980101")
    with session_scope() as db:
        assert identity.resolve_customer_session(db, token) is None
        row = db.execute(select(CustomerSession).where(CustomerSession.token_hash == crypto.hash_token(token))).scalar_one()
        assert row.channel == "magic" and row.token_hash != token
    assert client.get("/api/v1/me/profile", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    response = client.get("/api/v1/me/auth/magic-verify", params={"token": token}, headers=CSRF)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}  # No bearer credential exposed to browser JavaScript.
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api/v1" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    profile = client.get("/api/v1/me/profile")
    assert profile.status_code == 200 and profile.json()["customer"]["id"] == str(customer_id)
    for path in ("/needs", "/documents", "/auth/session"):
        assert client.get("/api/v1/me" + path).status_code == 200
    assert client.get("/api/v1/me/auth/magic-verify", params={"token": token}, headers=CSRF).status_code == 401
    assert client.get("/api/v1/inst/opportunities").status_code == 401


def test_expired_magic_and_cross_origin_exchange_do_not_create_a_session(client):
    token, _ = magic("+256772980102")
    denied = client.get("/api/v1/me/auth/magic-verify", params={"token": token},
                        headers={**CSRF, "Origin": "https://attacker.example"})
    assert denied.status_code == 403 and auth.COOKIE not in client.cookies
    with session_scope() as db:
        row = db.execute(select(CustomerSession).where(CustomerSession.token_hash == crypto.hash_token(token))).scalar_one()
        assert not row.revoked  # CSRF rejection did not consume the intended customer's credential.
        row.expires_at = utcnow() - timedelta(seconds=1)
    assert client.get("/api/v1/me/auth/magic-verify", params={"token": token}, headers=CSRF).status_code == 401
    assert auth.COOKIE not in client.cookies


def test_cookie_mutations_require_csrf_and_logout_revokes_session(client):
    token, _ = magic("+256772980103")
    client.get("/api/v1/me/auth/magic-verify", params={"token": token}, headers=CSRF)
    session_token = client.cookies.get(auth.COOKIE)
    assert client.put("/api/v1/me/preferences", json={}).status_code == 403
    assert client.put("/api/v1/me/preferences", json={}, headers={**CSRF, "Origin": "https://evil.example"}).status_code == 403
    assert client.put("/api/v1/me/preferences", json={}, headers=CSRF).status_code == 200
    assert client.post("/api/v1/me/auth/logout", headers=CSRF).status_code == 200
    assert client.get("/api/v1/me/auth/session").status_code == 401
    with session_scope() as db:
        assert identity.resolve_customer_session(db, session_token) is None


def test_phone_otp_creates_cookie_and_cannot_be_replayed_or_rebound(client):
    body = {"phone": "0772980104"}
    challenge = client.post("/api/v1/me/auth/otp/request", json=body, headers=CSRF)
    assert challenge.status_code == 200, challenge.text
    issued = challenge.json()
    verify = {**body, "challenge_id": issued["challenge_id"], "code": issued["dev_code"]}
    assert client.post("/api/v1/me/auth/otp/verify", json={**verify, "phone": "0772980199"}, headers=CSRF).status_code == 401
    response = client.post("/api/v1/me/auth/otp/verify", json=verify, headers=CSRF)
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert client.get("/api/v1/me/profile").status_code == 200
    assert client.post("/api/v1/me/auth/otp/verify", json=verify, headers=CSRF).status_code == 401


def test_otp_bad_attempts_survive_request_rollback_and_lock_out(client):
    body = {"phone": "0772980105"}
    issued = client.post("/api/v1/me/auth/otp/request", json=body, headers=CSRF).json()
    wrong = "000000" if issued["dev_code"] != "000000" else "111111"
    verify = {**body, "challenge_id": issued["challenge_id"], "code": wrong}
    for _ in range(get_settings().otp_max_attempts):
        response = client.post("/api/v1/me/auth/otp/verify", json=verify, headers=CSRF)
        assert response.status_code == 401
    assert response.json()["error"]["code"] == "OTP_LOCKED"
    assert client.post("/api/v1/me/auth/otp/verify", json={**verify, "code": issued["dev_code"]}, headers=CSRF).json()["error"]["code"] == "OTP_LOCKED"
    assert auth.COOKIE not in client.cookies


def test_journey_otp_cannot_be_used_for_browser_login(client):
    with session_scope() as db:
        issued = identity.issue_otp(db, "+256772980106")
        challenge_id, code = str(issued.challenge.id), issued.dev_code
    response = client.post("/api/v1/me/auth/otp/verify", headers=CSRF,
                           json={"phone": "0772980106", "challenge_id": challenge_id, "code": code})
    assert response.status_code == 401
    with session_scope() as db:
        challenge = db.execute(select(OtpChallenge).where(OtpChallenge.id == challenge_id)).scalar_one()
        assert challenge.status == "PENDING"


def test_customer_cookie_is_secure_in_production_and_staging(monkeypatch):
    for environment in ("production", "uat", "dev"):
        monkeypatch.setattr(get_settings(), "env", environment)
        response = Response()
        auth.set_session_cookie(response, "cs_test")
        assert "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
