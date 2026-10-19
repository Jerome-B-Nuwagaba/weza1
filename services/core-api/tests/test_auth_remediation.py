"""Regression coverage for MFA replacement, refresh reuse and password-reset session invalidation."""

import uuid

import pyotp
import pytest
from sqlalchemy import select
from starlette.requests import Request

from weza.api.deps import require_customer_csrf
from weza.config import get_settings
from weza.domains.identity import service as identity
from weza.domains.identity.models import RefreshToken, User
from weza.platform import crypto
from weza.platform.db import session_scope
from weza.platform.errors import Forbidden

PASSWORD = "OriginalPassword!2026"
NEW_PASSWORD = "ReplacementPassword!2026"


@pytest.fixture
def staff_user(monkeypatch):
    monkeypatch.setattr(get_settings(), "mfa_enforced", False)
    with session_scope() as db:
        user = identity.create_user(db, email=f"auth-{uuid.uuid4().hex}@example.test", full_name="Auth Test",
                                    password=PASSWORD, kind="WEZA")
        return user.id, user.email


def _login(client, email):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _enrol(client, token):
    response = client.post("/api/v1/auth/mfa/enrol-pending", json={"mfa_token": token})
    assert response.status_code == 200, response.text
    secret = response.json()["secret"]
    response = client.post("/api/v1/auth/mfa/enrol-pending/confirm",
                           json={"mfa_token": token, "code": pyotp.TOTP(secret).now()})
    assert response.status_code == 200, response.text
    return secret, response.json()["access_token"]


def test_pending_login_cannot_replace_existing_mfa(client, staff_user, monkeypatch):
    uid, email = staff_user
    monkeypatch.setattr(get_settings(), "mfa_enforced", True)
    first = _login(client, email)
    secret, _ = _enrol(client, first["mfa_token"])
    password_only = _login(client, email)["mfa_token"]
    invalid_code = str((int(pyotp.TOTP(secret).now()) + 123456) % 1000000).zfill(6)
    for extra in ({}, {"existing_mfa_code": invalid_code}):
        response = client.post("/api/v1/auth/mfa/enrol-pending", json={"mfa_token": password_only, **extra})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "MFA_REQUIRED"
    with session_scope() as db:
        user = db.get(User, uid)
        assert user.mfa_enrolled
        assert crypto.decrypt_bytes(user.mfa_secret_ct, user.mfa_secret_key).decode() == secret
    # The legitimate current factor still works after both rejected replacement attempts.
    assert client.post("/api/v1/auth/mfa/verify", json={"mfa_token": password_only,
                                                      "code": pyotp.TOTP(secret).now()}).status_code == 200


def test_authenticated_mfa_rotation_requires_current_code(client, staff_user, monkeypatch):
    _, email = staff_user
    monkeypatch.setattr(get_settings(), "mfa_enforced", True)
    secret, access = _enrol(client, _login(client, email)["mfa_token"])
    headers = {"Authorization": f"Bearer {access}"}
    assert client.post("/api/v1/auth/mfa/enrol", headers=headers).status_code == 401
    response = client.post("/api/v1/auth/mfa/enrol", headers=headers,
                           json={"existing_mfa_code": pyotp.TOTP(secret).now()})
    assert response.status_code == 200
    replacement = response.json()["secret"]
    assert replacement != secret
    assert client.post("/api/v1/auth/mfa/enrol/confirm", headers=headers,
                       json={"code": pyotp.TOTP(replacement).now()}).status_code == 200


def test_pending_mfa_rotation_accepts_current_code(client, staff_user, monkeypatch):
    _, email = staff_user
    monkeypatch.setattr(get_settings(), "mfa_enforced", True)
    secret, _ = _enrol(client, _login(client, email)["mfa_token"])
    token = _login(client, email)["mfa_token"]
    response = client.post("/api/v1/auth/mfa/enrol-pending",
                           json={"mfa_token": token, "existing_mfa_code": pyotp.TOTP(secret).now()})
    assert response.status_code == 200
    assert response.json()["secret"] != secret


def test_refresh_reuse_revocation_survives_error_rollback(client, staff_user):
    uid, email = staff_user
    original = _login(client, email)["refresh_token"]
    independent = _login(client, email)["refresh_token"]
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200
    replacement = rotated.json()["refresh_token"]
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "REFRESH_REUSED"
    # A fresh transaction observes the revocation even though the replay returned an exception.
    with session_scope() as db:
        tokens = db.execute(select(RefreshToken).where(RefreshToken.user_id == uid)).scalars().all()
        reused = next(row for row in tokens if row.token_hash == crypto.hash_token(original))
        assert all(row.revoked for row in tokens if row.family == reused.family)
        assert len([row for row in tokens if row.family == reused.family]) == 2
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": replacement}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": independent}).status_code == 200


def test_password_reset_invalidates_access_and_refresh_tokens(client, staff_user):
    uid, email = staff_user
    tokens = _login(client, email)
    assert crypto.verify_jwt(tokens["access_token"])["token_version"] == 1
    legacy = crypto.sign_jwt({"sub": str(uid), "typ": "access", "kind": "WEZA", "mfa": False}, 15)
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 200
    with session_scope() as db:
        user = db.get(User, uid)
        identity.set_password(db, user, NEW_PASSWORD)
        assert user.token_version == 2
    for token in (tokens["access_token"], legacy):
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_EXPIRED"
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    replacement = client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
    assert replacement.status_code == 200
    current = replacement.json()["access_token"]
    assert crypto.verify_jwt(current)["token_version"] == 2
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {current}"}).status_code == 200


def test_password_reset_invalidates_pending_mfa_challenges(client, staff_user, monkeypatch):
    uid, email = staff_user
    monkeypatch.setattr(get_settings(), "mfa_enforced", True)
    token = _login(client, email)["mfa_token"]
    with session_scope() as db:
        identity.set_password(db, db.get(User, uid), NEW_PASSWORD)
    response = client.post("/api/v1/auth/mfa/enrol-pending", json={"mfa_token": token})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.parametrize("version", [0, 2, "1", True])
def test_invalid_access_token_versions_are_rejected(client, staff_user, version):
    uid, _ = staff_user
    token = crypto.sign_jwt({"sub": str(uid), "typ": "access", "token_version": version}, 15)
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.parametrize("headers", [
    {"origin": "https://attacker.example", "x-weza-csrf": "1"},
    {"origin": "http://localhost:3000"},
    {"origin": "null", "referer": "http://localhost:3000/start", "x-weza-csrf": "1"},
])
def test_customer_csrf_rejects_untrusted_or_missing_proof(headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_web_url", "http://localhost:3000")
    monkeypatch.setattr(get_settings(), "cors_origins", "http://localhost:3000")
    request = Request({"type": "http", "headers": [(key.encode(), value.encode()) for key, value in headers.items()]})
    with pytest.raises(Forbidden, match="return to WEZA"):
        require_customer_csrf(request)


def test_customer_csrf_allows_same_origin_get_referrer(monkeypatch):
    monkeypatch.setattr(get_settings(), "public_web_url", "http://localhost:3000")
    request = Request({"type": "http", "headers": [(b"referer", b"http://localhost:3000/start"),
                                                    (b"x-weza-csrf", b"1")]})
    require_customer_csrf(request)
