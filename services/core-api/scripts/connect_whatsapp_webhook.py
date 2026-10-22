"""Check, then optionally connect the existing Meta app to a WEZA API.

From services/core-api:
    python scripts/connect_whatsapp_webhook.py --api-base-url https://your-api.example
    python scripts/connect_whatsapp_webhook.py --api-base-url https://your-api.example --apply

The default only reads configuration and probes the API with an empty webhook (no
customer messages). --apply updates the WhatsApp app subscription and, if absent,
subscribes this app to its configured WABA. It never sends messages or registers a
number. Existing callback overrides that route elsewhere block the change.

References:
https://developers.facebook.com/docs/graph-api/reference/application/subscriptions/
https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/override/
"""

import argparse
import hashlib
import hmac
import json
import logging
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weza.config import get_settings, is_configured  # noqa: E402

WEBHOOK_PATH = "/api/v1/channels/whatsapp/webhook"
REQUIRED_FIELDS = {"messages", "account_update"}
REQUIRED_SCOPES = {"whatsapp_business_messaging", "whatsapp_business_management"}


class CheckFailed(Exception):
    """Only fixed labels and numeric status codes belong in this exception."""


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise CheckFailed(label)


def _base_url(value: str) -> str:
    try:
        u = urlsplit(value)
        valid = (u.scheme == "https" and u.hostname and not u.username and not u.password
                 and not u.query and not u.fragment and u.path in ("", "/") and u.port in (None, 443))
    except ValueError:
        valid = False
    _require(bool(valid), "API_BASE_URL_MUST_BE_AN_HTTPS_ORIGIN")
    return value.rstrip("/")


def _request(client, method: str, url: str, label: str, **kwargs) -> httpx.Response:
    try:
        return client.request(method, url, timeout=30, follow_redirects=False, **kwargs)
    except httpx.HTTPError:
        raise CheckFailed(f"{label}:NETWORK_ERROR") from None


def _json(response: httpx.Response, label: str) -> dict:
    _require(response.status_code == 200, f"{label}:HTTP_{response.status_code}")
    try:
        value = response.json()
    except ValueError:
        raise CheckFailed(f"{label}:INVALID_JSON") from None
    _require(isinstance(value, dict), f"{label}:UNEXPECTED_RESPONSE")
    _require("error" not in value, f"{label}:META_ERROR")
    return value


class Graph:
    def __init__(self, settings, client):
        self.s, self.client = settings, client
        self.base = f"https://graph.facebook.com/{settings.graph_api_version}"

    def call(self, method: str, path: str, label: str, *, app: bool = False, **kwargs) -> dict:
        token = f"{self.s.whatsapp_app_id}|{self.s.whatsapp_app_secret}" if app else self.s.whatsapp_token
        response = _request(self.client, method, f"{self.base}/{path}", label,
                            headers={"Authorization": f"Bearer {token}"}, **kwargs)
        return _json(response, label)

    def rows(self, path: str, label: str, *, app: bool = False, params: dict | None = None) -> list[dict]:
        """Follow cursors on the same Graph endpoint, never provider-supplied URLs."""
        rows, query = [], {"limit": 100, **(params or {})}
        for _ in range(20):
            value = self.call("GET", path, label, app=app, params=query)
            data = value.get("data")
            _require(isinstance(data, list) and all(isinstance(row, dict) for row in data),
                     f"{label}:UNEXPECTED_RESPONSE")
            rows.extend(data)
            paging = value.get("paging") or {}
            _require(isinstance(paging, dict), f"{label}:INVALID_PAGINATION")
            if not paging.get("next"):
                return rows
            cursors = paging.get("cursors") or {}
            after = cursors.get("after") if isinstance(cursors, dict) else None
            _require(isinstance(after, str) and bool(after) and after != query.get("after"),
                     f"{label}:INVALID_PAGINATION")
            query = {**query, "after": after}
        raise CheckFailed(f"{label}:PAGINATION_LIMIT")


def _target_checks(s, client, base: str, checks: list[str]) -> None:
    for path in ("/healthz", "/api/v1/health"):
        health = _json(_request(client, "GET", base + path, "API_HEALTH"), "API_HEALTH")
        _require(health.get("status") == "ok", "API_HEALTH:NOT_OK")
    checks.append("api_and_database_healthy")
    config = _json(_request(client, "GET", base + "/api/v1/public/config", "API_CONFIG"), "API_CONFIG")
    _require(config.get("whatsapp_live") is True, "API_WHATSAPP_OUTBOUND_NOT_CONFIGURED")
    if s.whatsapp_business_number:
        expected = re.sub(r"\D", "", s.whatsapp_business_number)
        _require(config.get("whatsapp_number") == expected, "API_BUSINESS_NUMBER_MISMATCH")
    checks.append("api_whatsapp_sending_configured")
    callback, challenge = base + WEBHOOK_PATH, uuid.uuid4().hex
    params = {"hub.mode": "subscribe", "hub.verify_token": s.whatsapp_verify_token, "hub.challenge": challenge}
    response = _request(client, "GET", callback, "WEBHOOK_CHALLENGE", params=params)
    _require(response.status_code == 200 and response.text == challenge, "WEBHOOK_CHALLENGE_REJECTED")
    params["hub.verify_token"] = s.whatsapp_verify_token + ".invalid"
    response = _request(client, "GET", callback, "WEBHOOK_BAD_TOKEN", params=params)
    _require(response.status_code == 403, "WEBHOOK_BAD_TOKEN_NOT_REJECTED")
    raw = b'{"object":"whatsapp_business_account","entry":[]}'
    signature = "sha256=" + hmac.new(s.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-Hub-Signature-256": signature}
    response = _request(client, "POST", callback, "WEBHOOK_SIGNATURE", content=raw, headers=headers)
    _require(response.status_code == 200 and _json(response, "WEBHOOK_SIGNATURE").get("ok") is True,
             "WEBHOOK_SIGNATURE_REJECTED")
    headers["X-Hub-Signature-256"] = signature[:-1] + ("0" if signature[-1] != "0" else "1")
    response = _request(client, "POST", callback, "WEBHOOK_BAD_SIGNATURE", content=raw, headers=headers)
    _require(response.status_code == 403, "WEBHOOK_BAD_SIGNATURE_NOT_REJECTED")
    checks.append("webhook_verification_and_signature_checks_passed")


def _account_checks(s, graph: Graph, checks: list[str]) -> None:
    value = graph.call("GET", "debug_token", "META_TOKEN", app=True, params={"input_token": s.whatsapp_token})
    token = value.get("data") or {}
    _require(isinstance(token, dict) and token.get("is_valid") is True, "META_TOKEN_INVALID")
    _require(str(token.get("app_id")) == s.whatsapp_app_id, "META_TOKEN_APP_MISMATCH")
    scopes = token.get("scopes") or []
    _require(isinstance(scopes, list) and REQUIRED_SCOPES.issubset(scopes), "META_TOKEN_MISSING_PERMISSIONS")
    proof = hmac.new(s.whatsapp_app_secret.encode(), s.whatsapp_token.encode(), hashlib.sha256).hexdigest()
    me = graph.call("GET", "me", "META_APP_SECRET_PROOF", params={"fields": "id", "appsecret_proof": proof})
    _require(bool(me.get("id")), "META_APP_SECRET_PROOF_FAILED")
    checks.append("meta_token_permissions_and_app_secret_verified")
    numbers = graph.rows(f"{s.whatsapp_business_account_id}/phone_numbers", "META_WABA_NUMBERS",
                         params={"fields": "id,display_phone_number,platform_type,code_verification_status"})
    phone = next((row for row in numbers if str(row.get("id")) == s.whatsapp_phone_number_id), None)
    _require(phone is not None, "META_PHONE_NOT_OWNED_BY_CONFIGURED_WABA")
    _require(phone.get("platform_type") == "CLOUD_API"
             and phone.get("code_verification_status") == "VERIFIED", "META_PHONE_NOT_READY")
    if s.whatsapp_business_number:
        _require(re.sub(r"\D", "", str(phone.get("display_phone_number") or ""))
                 == re.sub(r"\D", "", s.whatsapp_business_number), "META_BUSINESS_NUMBER_MISMATCH")
    checks.append("meta_waba_number_ownership_verified")


def _subscription(s, graph: Graph) -> tuple[dict | None, set[str]]:
    rows = graph.rows(f"{s.whatsapp_app_id}/subscriptions", "META_APP_SUBSCRIPTIONS", app=True)
    matches = [row for row in rows if row.get("object") == "whatsapp_business_account"]
    _require(len(matches) <= 1, "META_APP_SUBSCRIPTIONS_AMBIGUOUS")
    current, fields = matches[0] if matches else None, set()
    if current:
        old_fields = current.get("fields")
        _require(isinstance(old_fields, list), "META_SUBSCRIPTION_FIELDS_UNAVAILABLE")
        for field in old_fields:
            name = field.get("name") if isinstance(field, dict) else None
            _require(isinstance(name, str) and bool(re.fullmatch(r"[a-zA-Z0-9_]+", name)),
                     "META_SUBSCRIPTION_FIELDS_INVALID")
            fields.add(name)
    return current, fields


def _routing(s, graph: Graph, callback: str) -> bool:
    apps = graph.rows(f"{s.whatsapp_business_account_id}/subscribed_apps", "META_WABA_SUBSCRIPTIONS")
    subscribed = False
    for app in apps:
        info = app.get("whatsapp_business_api_data") or app
        _require(isinstance(info, dict) and bool(info.get("id")), "META_WABA_SUBSCRIPTIONS_INVALID")
        if str(info["id"]) == s.whatsapp_app_id:
            subscribed = True
            _require(app.get("override_callback_uri") in (None, "", callback), "META_WABA_CALLBACK_OVERRIDE_CONFLICT")
    value = graph.call("GET", s.whatsapp_phone_number_id, "META_PHONE_WEBHOOK_CONFIGURATION",
                       params={"fields": "webhook_configuration"})
    config = value.get("webhook_configuration")
    _require(isinstance(config, dict), "META_PHONE_WEBHOOK_CONFIGURATION_UNAVAILABLE")
    for field in ("phone_number", "whatsapp_business_account"):
        _require(config.get(field) in (None, "", callback), "META_PHONE_CALLBACK_OVERRIDE_CONFLICT")
    return subscribed


def connect(settings, api_base_url: str, *, apply: bool = False, client=None) -> dict:
    """Return a sanitized plan/result. Inject an httpx client for tests; never return provider bodies."""
    report = {"status": "blocked", "checks": [], "changes": [], "attempted": [], "applied": []}
    own_client = client is None
    client = client or httpx.Client()
    try:
        base = _base_url(api_base_url)
        names = ("whatsapp_token", "whatsapp_app_id", "whatsapp_app_secret", "whatsapp_verify_token",
                 "whatsapp_phone_number_id", "whatsapp_business_account_id")
        missing = [name.upper() for name in names if not is_configured(getattr(settings, name, ""))]
        _require(not missing, "MISSING_SETTINGS:" + ",".join(missing))
        for name in ("whatsapp_app_id", "whatsapp_phone_number_id", "whatsapp_business_account_id"):
            _require(bool(re.fullmatch(r"\d+", getattr(settings, name))), f"INVALID_{name.upper()}")
        _require(bool(re.fullmatch(r"[0-9a-fA-F]{32}", settings.whatsapp_app_secret)), "INVALID_WHATSAPP_APP_SECRET_FORMAT")
        _target_checks(settings, client, base, report["checks"])
        graph, callback = Graph(settings, client), base + WEBHOOK_PATH
        _account_checks(settings, graph, report["checks"])
        subscription, existing_fields = _subscription(settings, graph)
        fields = existing_fields | REQUIRED_FIELDS
        subscribed = _routing(settings, graph, callback)
        report["checks"].append("existing_subscriptions_and_overrides_checked")
        update = (not subscription or subscription.get("callback_url") != callback
                  or subscription.get("active") is not True or not REQUIRED_FIELDS.issubset(existing_fields))
        if update:
            report["changes"].append("update_app_whatsapp_callback_and_fields")
        if not subscribed:
            report["changes"].append("subscribe_app_to_configured_waba")
        report["fields"] = sorted(fields)
        report["status"] = "ready" if report["changes"] else "connected"
        if not apply or not report["changes"]:
            return report
        if update:
            report["attempted"].append("update_app_whatsapp_subscription")
            result = graph.call("POST", f"{settings.whatsapp_app_id}/subscriptions", "META_UPDATE_SUBSCRIPTION",
                                app=True, data={"object": "whatsapp_business_account", "callback_url": callback,
                                                "verify_token": settings.whatsapp_verify_token,
                                                "fields": ",".join(sorted(fields)), "include_values": "true"})
            _require(result.get("success") is True, "META_UPDATE_SUBSCRIPTION_NOT_CONFIRMED")
            report["applied"].append("updated_app_whatsapp_subscription")
        # Do not enable delivery to a WABA until the app callback update is visible.
        current, actual_fields = _subscription(settings, graph)
        _require(bool(current) and current.get("callback_url") == callback and current.get("active") is True
                 and fields.issubset(actual_fields), "META_SUBSCRIPTION_READBACK_FAILED")
        # Recheck overrides before subscribing; a concurrent subscription must not be overwritten.
        if not subscribed and not _routing(settings, graph, callback):
            report["attempted"].append("subscribe_app_to_waba")
            result = graph.call("POST", f"{settings.whatsapp_business_account_id}/subscribed_apps", "META_SUBSCRIBE_WABA")
            _require(result.get("success") is True, "META_SUBSCRIBE_WABA_NOT_CONFIRMED")
            report["applied"].append("subscribed_app_to_waba")
        current, actual_fields = _subscription(settings, graph)
        _require(bool(current) and current.get("callback_url") == callback and current.get("active") is True
                 and fields.issubset(actual_fields), "META_SUBSCRIPTION_READBACK_FAILED")
        _require(_routing(settings, graph, callback), "META_WABA_SUBSCRIPTION_READBACK_FAILED")
        report["status"] = "connected"
    except CheckFailed as exc:
        report.update(status="failed" if report["attempted"] else "blocked", error=str(exc))
    except Exception as exc:  # never expose HTTP URLs, provider bodies or credential values in a traceback
        report.update(status="failed" if report["attempted"] else "blocked", error=f"CHECK_ERROR:{type(exc).__name__}")
    finally:
        if own_client:
            client.close()
    return report


def main(argv=None) -> int:
    # httpx INFO logging includes query strings (the debug-token endpoint requires an input_token).
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", required=True, help="Explicit HTTPS API origin, without a path")
    parser.add_argument("--apply", action="store_true", help="Apply the checked Meta subscription changes")
    args = parser.parse_args(argv)
    try:
        report = connect(get_settings(), args.api_base_url, apply=args.apply)
    except Exception as exc:
        report = {"status": "blocked", "error": f"SETTINGS_ERROR:{type(exc).__name__}"}
    print(json.dumps(report, indent=2))
    return 0 if report["status"] in ("ready", "connected") else 1


if __name__ == "__main__":
    raise SystemExit(main())
