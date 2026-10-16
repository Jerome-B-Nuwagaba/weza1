"""Embedded Signup (coexistence) onboarding: admin-only, code exchange, WABA check, webhook subscription, number status.

Everything Meta-side is a local fake: no request leaves the machine. Credentials are FAKE."""

import json
import logging

import httpx
import pytest
from sqlalchemy import select

from tests.helpers import login
from weza.config import get_settings
from weza.domains.trust.models import AuditEvent
from weza.platform.db import session_scope

URL = "/api/v1/admin/whatsapp/embedded-signup"
BUSINESS_TOKEN = "FAKE_BUSINESS_TOKEN_must_never_leave_the_server"
APP_SECRET = "0123456789abcdef0123456789abcdef"
WABA = "111222333444"


class FakeMeta:
    def __init__(self):
        self.calls: list[dict] = []
        self.exchange_ok, self.subscribe_ok = True, True
        self.granted = [WABA]
        self.numbers = [{"id": "555666777888", "display_phone_number": "+256 700 000 123", "verified_name": "Weza",
                         "platform_type": "CLOUD_API", "is_on_biz_app": True, "code_verification_status": "VERIFIED"}]

    def _path(self, url: str) -> str:
        assert url.startswith("https://graph.facebook.com/"), url
        return url.split("graph.facebook.com/", 1)[1].split("/", 1)[1]

    def _resp(self, method, url, status, data):
        return httpx.Response(status, json=data, request=httpx.Request(method, url))

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        path = self._path(url)
        self.calls.append({"m": "GET", "path": path, "params": params or {}, "headers": headers or {}})
        if path == "oauth/access_token":
            if not self.exchange_ok:
                return self._resp("GET", url, 400, {"error": {"code": 100, "error_subcode": 36007,
                                                              "message": "code expired"}})
            return self._resp("GET", url, 200, {"access_token": BUSINESS_TOKEN, "token_type": "bearer"})
        if path == "debug_token":
            return self._resp("GET", url, 200, {"data": {"is_valid": True, "granular_scopes": [
                {"scope": "whatsapp_business_management", "target_ids": self.granted},
                {"scope": "whatsapp_business_messaging", "target_ids": self.granted}]}})
        if path.endswith("/phone_numbers"):
            return self._resp("GET", url, 200, {"data": self.numbers})
        return self._resp("GET", url, 404, {"error": {"code": 803}})

    def post(self, url, params=None, json=None, headers=None, timeout=None, **kw):
        path = self._path(url)
        self.calls.append({"m": "POST", "path": path, "params": params or {}, "headers": headers or {}})
        if path.endswith("/subscribed_apps"):
            return self._resp("POST", url, 200 if self.subscribe_ok else 400,
                              {"success": True} if self.subscribe_ok else {"error": {"code": 200}})
        return self._resp("POST", url, 404, {"error": {"code": 803}})


_tokens: dict[str, dict] = {}


@pytest.fixture()
def as_user(client):
    """Sign in once per account for this module: the login endpoint is rate limited per account."""
    def _as(email: str) -> dict:
        if email not in _tokens:
            _tokens[email] = login(client, email)
        return _tokens[email]
    return _as


@pytest.fixture()
def meta(monkeypatch):
    fake = FakeMeta()
    monkeypatch.setattr(httpx, "get", fake.get)
    monkeypatch.setattr(httpx, "post", fake.post)
    return fake


@pytest.fixture()
def es(monkeypatch):
    s = get_settings()
    for k, v in {"whatsapp_app_id": "1234567890", "whatsapp_embedded_signup_config_id": "9876543210",
                 "whatsapp_app_secret": APP_SECRET, "whatsapp_business_number": "256700000123"}.items():
        monkeypatch.setattr(s, k, v)
    return s


def connect(client, as_user, **body):
    return client.post(URL, json={"code": "FAKE_CODE_0123456789", "waba_id": WABA,
                                  "event": "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING", **body},
                       headers=as_user("admin@weza.demo"))


def test_launch_config_lists_missing_settings_by_name(client, as_user):
    r = client.get(URL, headers=as_user("admin@weza.demo"))
    assert r.status_code == 200
    j = r.json()
    assert j["ready"] is False and j["app_id"] is None
    assert set(j["missing"]) == {"WHATSAPP_APP_ID", "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", "WHATSAPP_APP_SECRET"}


def test_launch_config_when_ready_never_exposes_the_secret(client, as_user, es):
    j = client.get(URL, headers=as_user("admin@weza.demo")).json()
    assert j["ready"] is True and j["app_id"] == "1234567890" and j["config_id"] == "9876543210"
    assert j["feature_type"] == "whatsapp_business_app_onboarding" and j["session_info_version"] == "3"
    assert APP_SECRET not in json.dumps(j)


@pytest.mark.parametrize("email", ["ops@weza.demo", "commercial@weza.demo"])
def test_only_weza_super_admins_can_use_it(client, as_user, es, meta, email):
    h = as_user(email)
    assert client.get(URL, headers=h).status_code == 403
    assert client.post(URL, json={"code": "FAKE_CODE_0123456789"}, headers=h).status_code == 403
    assert meta.calls == []


def test_institution_users_and_anonymous_are_refused(client, as_user, es, meta):
    assert client.post(URL, json={"code": "FAKE_CODE_0123456789"}).status_code == 401
    assert client.post(URL, json={"code": "FAKE_CODE_0123456789"},
                       headers=as_user("admin@lakeside.demo")).status_code == 403
    assert meta.calls == []


def test_connect_exchanges_code_subscribes_and_reports_coexistence(client, as_user, es, meta, caplog):
    with caplog.at_level(logging.DEBUG):
        r = connect(client, as_user)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["waba_id"] == WABA and j["subscribed"] is True and j["coexistence"] is True and j["warnings"] == []
    assert j["settings"] == {"WHATSAPP_BUSINESS_ACCOUNT_ID": WABA, "WHATSAPP_PHONE_NUMBER_ID": "555666777888"}
    (n,) = j["phone_numbers"]
    assert n["number"] == "…123" and n["is_business_number"] is True

    exchange, debug, sub, nums = meta.calls
    assert exchange["path"] == "oauth/access_token" and exchange["params"] == {
        "client_id": "1234567890", "client_secret": APP_SECRET, "code": "FAKE_CODE_0123456789"}
    assert debug["path"] == "debug_token" and debug["headers"]["Authorization"] == f"Bearer 1234567890|{APP_SECRET}"
    assert (sub["m"], sub["path"]) == ("POST", f"{WABA}/subscribed_apps")
    assert sub["headers"]["Authorization"] == f"Bearer {BUSINESS_TOKEN}"
    assert nums["path"] == f"{WABA}/phone_numbers"
    assert not any(c["path"].endswith("/register") for c in meta.calls)  # coexistence: never register the number

    # The business token is used only server-side: not returned, not logged, not audited.
    assert BUSINESS_TOKEN not in r.text and APP_SECRET not in r.text
    logs = " ".join(r.getMessage() + str(getattr(r, "data", "")) for r in caplog.records)
    assert BUSINESS_TOKEN not in logs and APP_SECRET not in logs and "FAKE_CODE_0123456789" not in logs
    with session_scope() as db:
        ev = db.execute(select(AuditEvent).where(AuditEvent.action == "whatsapp.embedded_signup",
                                                 AuditEvent.object_id == WABA)).scalars().first()
        assert ev is not None and ev.after["phone_number_ids"] == ["555666777888"]
        assert BUSINESS_TOKEN not in json.dumps(ev.after)


def test_rejected_code_stops_before_touching_the_account(client, as_user, es, meta):
    meta.exchange_ok = False
    r = connect(client, as_user)
    assert r.status_code == 422 and r.json()["error"]["code"] == "ES_CODE_REJECTED"
    assert [c["path"] for c in meta.calls] == ["oauth/access_token"]


def test_waba_not_granted_to_the_app_is_refused(client, as_user, es, meta):
    meta.granted = ["999999999999"]
    r = connect(client, as_user)
    assert r.status_code == 422 and r.json()["error"]["code"] == "ES_WABA_MISMATCH"
    assert not any(c["m"] == "POST" for c in meta.calls)


def test_waba_is_found_from_the_token_when_the_window_message_was_missed(client, as_user, es, meta):
    r = connect(client, as_user, waba_id=None, event=None)
    assert r.status_code == 200 and r.json()["waba_id"] == WABA


def test_failed_subscription_and_non_coexistence_number_are_reported(client, as_user, es, meta):
    meta.subscribe_ok = False
    meta.numbers[0].update(is_on_biz_app=False)
    j = connect(client, as_user, event="FINISH").json()
    assert j["subscribed"] is False and j["coexistence"] is False
    text = " ".join(j["warnings"])
    assert "not a WhatsApp Business app (coexistence)" in text and "Subscribing" in text and "Do not register" in text


def test_not_configured_makes_no_meta_calls(client, as_user, meta):
    r = connect(client, as_user)
    assert r.status_code == 422 and r.json()["error"]["code"] == "ES_NOT_CONFIGURED"
    assert meta.calls == []


def test_bad_waba_id_is_rejected(client, as_user, es, meta):
    r = connect(client, as_user, waba_id="12; DROP")
    assert r.status_code == 422 and meta.calls == []
