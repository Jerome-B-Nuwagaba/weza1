"""Connection-helper checks use a mock transport; no Meta/API requests or customer sends occur."""

import hashlib
import hmac
import json
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from scripts import connect_whatsapp_webhook as connection

API = "https://api.example"
CALLBACK = API + connection.WEBHOOK_PATH


@pytest.fixture()
def settings():
    return SimpleNamespace(whatsapp_token="FAKE_outbound_token_private", whatsapp_app_id="123456",
                           whatsapp_app_secret="0123456789abcdef0123456789abcdef",
                           whatsapp_verify_token="FAKE_verify_token_private", whatsapp_phone_number_id="234567",
                           whatsapp_business_account_id="345678", whatsapp_business_number="256700000123",
                           graph_api_version="v25.0")


class FakeNetwork:
    def __init__(self, settings):
        self.s = settings
        self.failure = ""
        self.callback = "https://previous.example/webhook"
        self.fields = ["messages", "message_template_status_update"]
        self.subscribed = True
        self.override = None
        self.phone_override = None
        self.calls = []
        self.paginate_numbers = False
        self.client = httpx.Client(transport=httpx.MockTransport(self.request))

    @property
    def mutations(self):
        return [r for r in self.calls if r.url.host == "graph.facebook.com" and r.method == "POST"]

    def response(self, request, value=None, *, status=200, text=None):
        return httpx.Response(status, json=value, text=text, request=request)

    def request(self, request):
        self.calls.append(request)
        if request.url.host == "api.example":
            return self.api(request)
        assert request.url.host == "graph.facebook.com"
        path = request.url.path.removeprefix("/v25.0/")
        if self.failure == "network":
            raise httpx.ConnectError(self.s.whatsapp_token + " https://secret.example?access_token=PRIVATE")
        if path == "debug_token":
            return self.response(request, {"data": {
                "is_valid": self.failure != "token", "app_id": "999" if self.failure == "app" else self.s.whatsapp_app_id,
                "scopes": [] if self.failure == "scopes" else sorted(connection.REQUIRED_SCOPES)}})
        if path == "me":
            if self.failure == "proof":
                return self.response(request, {"error": {"message": self.s.whatsapp_app_secret}}, status=403)
            proof = hmac.new(self.s.whatsapp_app_secret.encode(), self.s.whatsapp_token.encode(), hashlib.sha256).hexdigest()
            assert request.url.params["appsecret_proof"] == proof
            return self.response(request, {"id": "456789"})
        if path == self.s.whatsapp_business_account_id + "/phone_numbers":
            if self.paginate_numbers and "after" not in request.url.params:
                return self.response(request, {"data": [], "paging": {
                    "next": "https://untrusted.example?access_token=PRIVATE", "cursors": {"after": "next-page"}}})
            numbers = [] if self.failure == "ownership" else [{
                "id": self.s.whatsapp_phone_number_id,
                "display_phone_number": "256799999999" if self.failure == "number" else self.s.whatsapp_business_number,
                "platform_type": "NOT_READY" if self.failure == "phone" else "CLOUD_API",
                "code_verification_status": "VERIFIED"}]
            return self.response(request, {"data": numbers})
        if path == self.s.whatsapp_app_id + "/subscriptions":
            if request.method == "POST":
                if self.failure == "mutation":
                    return self.response(request, {"error": {"message": self.s.whatsapp_token}}, status=403)
                data = parse_qs(request.content.decode())
                assert data["object"] == ["whatsapp_business_account"]
                assert data["verify_token"] == [self.s.whatsapp_verify_token]
                assert request.headers["Authorization"] == f"Bearer {self.s.whatsapp_app_id}|{self.s.whatsapp_app_secret}"
                if self.failure != "readback":
                    self.callback = data["callback_url"][0]
                    self.fields = data["fields"][0].split(",")
                return self.response(request, {"success": True})
            return self.response(request, {"data": [
                {"object": "page", "callback_url": "https://other.example/webhook", "fields": [{"name": "feed"}]},
                {"object": "whatsapp_business_account", "callback_url": self.callback, "active": True,
                 "fields": [{"name": name} for name in self.fields]}]})
        if path == self.s.whatsapp_business_account_id + "/subscribed_apps":
            if request.method == "POST":
                assert not request.content  # no override reset or number registration parameters
                if self.failure == "subscribe":
                    return self.response(request, {"error": {"message": self.s.whatsapp_token}}, status=400)
                self.subscribed = True
                return self.response(request, {"success": True})
            rows = [{"whatsapp_business_api_data": {"id": self.s.whatsapp_app_id},
                     "override_callback_uri": self.override}] if self.subscribed else []
            return self.response(request, {"data": rows})
        if path == self.s.whatsapp_phone_number_id:
            return self.response(request, {"webhook_configuration": {
                "application": self.callback, "phone_number": self.phone_override}})
        raise AssertionError("Unexpected request route")

    def api(self, request):
        path = request.url.path
        if path in ("/healthz", "/api/v1/health"):
            return self.response(request, {"status": "ok"}, status=503 if self.failure == "health" else 200)
        if path == "/api/v1/public/config":
            return self.response(request, {"whatsapp_live": self.failure != "outbound",
                                           "whatsapp_number": self.s.whatsapp_business_number})
        assert path == connection.WEBHOOK_PATH
        if request.method == "GET":
            valid = request.url.params["hub.verify_token"] == self.s.whatsapp_verify_token
            if valid:
                return self.response(request, text=request.url.params["hub.challenge"],
                                     status=403 if self.failure == "challenge" else 200)
            return self.response(request, text="denied", status=200 if self.failure == "bad_token" else 403)
        assert json.loads(request.content) == {"object": "whatsapp_business_account", "entry": []}
        signature = "sha256=" + hmac.new(self.s.whatsapp_app_secret.encode(), request.content, hashlib.sha256).hexdigest()
        valid = request.headers["X-Hub-Signature-256"] == signature
        status = (403 if self.failure == "signature" else 200) if valid else (200 if self.failure == "bad_signature" else 403)
        return self.response(request, {"ok": True}, status=status)


@pytest.fixture()
def network(settings):
    fake = FakeNetwork(settings)
    yield fake
    fake.client.close()


def run(settings, network, *, apply=False):
    return connection.connect(settings, API, apply=apply, client=network.client)


def test_default_only_checks_and_returns_concrete_plan(settings, network):
    result = run(settings, network)
    assert result["status"] == "ready"
    assert result["changes"] == ["update_app_whatsapp_callback_and_fields"]
    assert result["applied"] == [] and network.mutations == []
    assert result["fields"] == ["account_update", "message_template_status_update", "messages"]


def test_apply_preserves_existing_fields_and_existing_waba_subscription(settings, network):
    result = run(settings, network, apply=True)
    assert result["status"] == "connected"
    assert network.callback == CALLBACK
    assert set(network.fields) == {"messages", "message_template_status_update", "account_update"}
    assert len(network.mutations) == 1
    assert network.mutations[0].url.path.endswith("/subscriptions")


def test_apply_subscribes_waba_only_when_absent(settings, network):
    network.subscribed = False
    result = run(settings, network, apply=True)
    assert result["status"] == "connected"
    assert [r.url.path.split("/")[-1] for r in network.mutations] == ["subscriptions", "subscribed_apps"]
    assert len(result["applied"]) == 2


def test_connected_configuration_requires_no_mutations(settings, network):
    network.callback = CALLBACK
    network.fields.append("account_update")
    assert run(settings, network, apply=True)["status"] == "connected"
    assert network.mutations == []


@pytest.mark.parametrize("failure", ["health", "outbound", "challenge", "bad_token", "signature", "bad_signature",
                                     "token", "app", "scopes", "proof", "ownership", "number", "phone", "network"])
def test_failed_precondition_never_mutates_meta(settings, network, failure):
    network.failure = failure
    result = run(settings, network, apply=True)
    assert result["status"] == "blocked" and result["error"]
    assert network.mutations == []
    output = json.dumps(result)
    for private in (settings.whatsapp_token, settings.whatsapp_verify_token, settings.whatsapp_app_secret,
                    "secret.example", "PRIVATE"):
        assert private not in output


@pytest.mark.parametrize("scope", ["waba", "phone"])
def test_conflicting_callback_overrides_block_changes(settings, network, scope):
    if scope == "waba":
        network.override = "https://previous.example/override"
    else:
        network.phone_override = "https://previous.example/override"
    result = run(settings, network, apply=True)
    assert result["status"] == "blocked" and "OVERRIDE_CONFLICT" in result["error"]
    assert network.mutations == []


def test_matching_callback_override_is_preserved(settings, network):
    network.override = CALLBACK
    assert run(settings, network, apply=True)["status"] == "connected"
    assert network.override == CALLBACK and len(network.mutations) == 1


def test_pagination_stays_on_original_graph_endpoint(settings, network):
    network.paginate_numbers = True
    assert run(settings, network)["status"] == "ready"
    assert all(request.url.host in ("api.example", "graph.facebook.com") for request in network.calls)
    assert any(request.url.params.get("after") == "next-page" for request in network.calls)


@pytest.mark.parametrize("failure,applied", [("mutation", False), ("readback", True), ("subscribe", True)])
def test_provider_failures_and_incomplete_readback_never_report_connected(settings, network, failure, applied):
    network.failure = failure
    network.subscribed = failure != "subscribe"
    result = run(settings, network, apply=True)
    assert result["status"] in ("blocked", "failed")
    assert bool(result["applied"]) is applied
    assert settings.whatsapp_token not in json.dumps(result)


def test_callback_update_is_verified_before_enabling_waba_delivery(settings, network):
    network.failure, network.subscribed = "readback", False
    result = run(settings, network, apply=True)
    assert result["status"] == "failed" and result["error"] == "META_SUBSCRIPTION_READBACK_FAILED"
    assert not network.subscribed
    assert [r.url.path.split("/")[-1] for r in network.mutations] == ["subscriptions"]


@pytest.mark.parametrize("url", ["http://api.example", "https://user:password@api.example", "https://api.example/path",
                                  "https://api.example?access_token=private", "https://api.example/#fragment", ""])
def test_target_must_be_explicit_https_origin(settings, network, url):
    result = connection.connect(settings, url, apply=True, client=network.client)
    assert result["status"] == "blocked" and network.calls == []


def test_missing_settings_are_reported_by_name_only(settings, network):
    settings.whatsapp_token = ""
    result = run(settings, network, apply=True)
    assert result["error"] == "MISSING_SETTINGS:WHATSAPP_TOKEN"
    assert network.calls == []
