"""Microsoft Entra ID sign-in (TSD §13). Microsoft is faked with a real RSA key pair: tokens are properly signed, so the
checks that matter (signature, issuer, audience, nonce, state, unknown user, MFA) are exercised for real."""

import json
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from weza.config import get_settings
from weza.domains.identity import entra

TENANT = str(uuid.uuid4())
CLIENT = "weza-test-client"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(RSAAlgorithm.to_jwk(KEY.public_key())), "kid": "test-key", "use": "sig", "alg": "RS256"}


@pytest.fixture(autouse=True)
def entra_on(monkeypatch):
    s = get_settings()
    for k, v in {"entra_tenant_id": TENANT, "entra_client_id": CLIENT, "entra_client_secret": "shh",
                 "entra_redirect_uri": "http://localhost:3000/api/v1/auth/entra/callback"}.items():
        monkeypatch.setattr(s, k, v)
    entra._jwks.update(at=0.0, keys={})  # a fresh key cache for every test


def sign(nonce: str, *, email="manager@lakeside.demo", key=KEY, aud=CLIENT, iss=None, amr=None, exp=300) -> str:
    claims = {"iss": iss or f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": aud, "tid": TENANT,
              "iat": int(time.time()), "exp": int(time.time()) + exp, "nonce": nonce, "preferred_username": email,
              "amr": amr if amr is not None else ["pwd"]}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture()
def microsoft(monkeypatch):
    """Fake Microsoft: the key set endpoint and the token endpoint. `reply["id_token"]` is what the token endpoint returns."""
    reply: dict = {}

    def fake_get(url, **kw):
        assert url.endswith(f"/{TENANT}/discovery/v2.0/keys")
        return httpx.Response(200, json={"keys": [JWK]}, request=httpx.Request("GET", url))

    def fake_post(url, **kw):
        assert url.endswith(f"/{TENANT}/oauth2/v2.0/token")
        data = kw["data"]
        assert data["client_secret"] == "shh" and data["code_verifier"] and data["grant_type"] == "authorization_code"
        return httpx.Response(200, json={"id_token": reply["id_token"]} if "id_token" in reply else {"error": "x"},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    return reply


def start(client, next_path=None):
    r = client.get("/api/v1/auth/entra/start", params={"next": next_path} if next_path else {}, follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    state = q["state"][0]
    assert r.headers["set-cookie"].split(";")[0] == f"weza_entra={state}"  # the state is also in an HttpOnly cookie
    return r, q, state


def callback(client, state, *, cookie=None, code="auth-code"):
    return client.get("/api/v1/auth/entra/callback", params={"code": code, "state": state}, follow_redirects=False,
                      headers={"Cookie": f"weza_entra={cookie if cookie is not None else state}"})


def landing(r) -> dict:
    assert r.status_code == 302
    return {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}


def test_the_login_page_only_offers_microsoft_when_it_is_configured(client, monkeypatch):
    assert client.get("/api/v1/auth/entra/config").json() == {"enabled": True}
    monkeypatch.setattr(get_settings(), "entra_client_secret", None)
    assert client.get("/api/v1/auth/entra/config").json() == {"enabled": False}
    assert client.get("/api/v1/auth/entra/start", follow_redirects=False).status_code == 422


def test_a_multi_tenant_authority_is_refused(client, monkeypatch):
    """Matching users by email is only safe for a tenant we trust, so 'common' and friends are never accepted."""
    for authority in ("common", "organizations", "consumers", "contoso.onmicrosoft.com"):
        monkeypatch.setattr(get_settings(), "entra_tenant_id", authority)
        assert client.get("/api/v1/auth/entra/config").json() == {"enabled": False}


def test_start_sends_the_browser_to_microsoft_with_pkce_and_a_signed_state(client):
    r, q, state = start(client)
    assert urlparse(r.headers["location"]).netloc == "login.microsoftonline.com"
    assert q["client_id"] == [CLIENT] and q["code_challenge_method"] == ["S256"] and q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["http://localhost:3000/api/v1/auth/entra/callback"]
    claims = jwt.decode(state, get_settings().secret_key, algorithms=["HS256"], issuer="weza")
    assert claims["nonce"] == q["nonce"][0] and claims["typ"] == "entra" and len(claims["cv"]) > 40


def test_a_known_user_signs_in_and_gets_a_normal_weza_session(client, microsoft):
    _, q, state = start(client, "/institution/feed")
    microsoft["id_token"] = sign(q["nonce"][0], amr=["pwd", "mfa"])
    r = callback(client, state)
    assert landing(r) == {"next": "/institution/feed", "sso": "1"}
    refresh = r.headers["set-cookie"].split("weza_rt=")[1].split(";")[0]
    session = client.post("/api/v1/auth/refresh", json={}, headers={"Cookie": f"weza_rt={refresh}"}).json()
    assert session["user"]["email"] == "manager@lakeside.demo" and session["user"]["mfa"] is True
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session['access_token']}"}).status_code == 200
    # the one-time state cookie is cleared
    assert "weza_entra=" in r.headers.get_list("set-cookie")[-1]


@pytest.mark.parametrize("problem", ["aud", "iss", "nonce", "signature", "expired"])
def test_a_token_that_is_not_exactly_right_is_refused(client, microsoft, problem):
    _, q, state = start(client)
    nonce = q["nonce"][0]
    microsoft["id_token"] = {
        "aud": lambda: sign(nonce, aud="someone-elses-app"),
        "iss": lambda: sign(nonce, iss="https://login.microsoftonline.com/another-tenant/v2.0"),
        "nonce": lambda: sign("a-replayed-nonce"),
        "signature": lambda: sign(nonce, key=OTHER_KEY),
        "expired": lambda: sign(nonce, exp=-60),
    }[problem]()
    r = callback(client, state)
    assert landing(r)["sso_error"].startswith("ENTRA_") and "weza_rt" not in r.headers.get("set-cookie", "")


def test_a_microsoft_user_without_a_weza_account_gets_nothing_and_is_audited(client, microsoft):
    from sqlalchemy import select

    from weza.domains.trust.models import AuditEvent
    from weza.platform.db import session_scope
    _, q, state = start(client)
    microsoft["id_token"] = sign(q["nonce"][0], email="stranger@example.com")
    r = callback(client, state)
    assert landing(r) == {"sso_error": "ENTRA_NO_ACCOUNT"} and "weza_rt" not in r.headers.get("set-cookie", "")
    with session_scope() as db:
        assert db.execute(select(AuditEvent).where(AuditEvent.action == "auth.entra_denied")).first() is not None


def test_a_disabled_weza_user_cannot_sign_in_through_microsoft(client, microsoft):
    from sqlalchemy import select

    from weza.domains.identity.models import User
    from weza.platform.db import session_scope
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == "officer@kijani.demo")).scalar_one()
        user.status = "DISABLED"
    try:
        _, q, state = start(client)
        microsoft["id_token"] = sign(q["nonce"][0], email="officer@kijani.demo")
        assert landing(callback(client, state)) == {"sso_error": "ENTRA_NO_ACCOUNT"}
    finally:
        with session_scope() as db:
            db.execute(select(User).where(User.email == "officer@kijani.demo")).scalar_one().status = "ACTIVE"


def test_the_state_must_match_the_cookie_and_cannot_be_forged_or_replayed_elsewhere(client, microsoft):
    _, q, state = start(client)
    microsoft["id_token"] = sign(q["nonce"][0])
    _, _, other_state = start(client)
    assert landing(callback(client, state, cookie=other_state)) == {"sso_error": "ENTRA_STATE_MISMATCH"}
    assert landing(client.get("/api/v1/auth/entra/callback", params={"code": "c", "state": state},
                              follow_redirects=False)) == {"sso_error": "ENTRA_STATE_MISMATCH"}  # no cookie at all
    forged = jwt.encode({"typ": "entra", "nonce": q["nonce"][0], "cv": "x" * 50, "iss": "weza"}, "not-our-secret",
                        algorithm="HS256")
    assert landing(callback(client, forged))["sso_error"] == "ENTRA_STATE_EXPIRED"


def test_the_sign_in_cannot_be_used_as_an_open_redirect(client, microsoft):
    for evil in ("//evil.example/x", "https://evil.example", "/a" + chr(92) + "b"):
        _, q, state = start(client, evil)
        microsoft["id_token"] = sign(q["nonce"][0])
        assert "next" not in landing(callback(client, state))


def test_cancelling_at_microsoft_returns_to_the_login_page(client):
    r = client.get("/api/v1/auth/entra/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert landing(r) == {"sso_error": "ENTRA_CANCELLED"}


def test_without_microsoft_mfa_wezas_own_second_step_still_applies(client, microsoft, monkeypatch):
    monkeypatch.setattr(get_settings(), "mfa_enforced", True)
    _, q, state = start(client)
    microsoft["id_token"] = sign(q["nonce"][0], amr=["pwd"])  # Microsoft did not do MFA
    out = landing(callback(client, state))
    assert out["enrol"] == "1" and out["sso_mfa"] and "sso" not in out  # continues on the login page, no session yet
    _, q, state = start(client)
    microsoft["id_token"] = sign(q["nonce"][0], amr=["pwd", "mfa"])  # Microsoft did
    assert landing(callback(client, state)) == {"sso": "1"}
