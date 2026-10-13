"""DEV ONLY: replay Meta-style WhatsApp webhook payloads against your LOCAL API.

Signs with a clearly FAKE app secret, so the API terminal must use the same fake values (see FAKE_* below).
It never reads WHATSAPP_* from the environment or any .env file, refuses non-local URLs, and prints only
safe summaries (status codes, no phone numbers or message text).

Usage (from services/core-api):
    .venv\\Scripts\\python scripts\\replay_whatsapp_webhook.py verify
    .venv\\Scripts\\python scripts\\replay_whatsapp_webhook.py text --text "I need 5 million for stock"
    .venv\\Scripts\\python scripts\\replay_whatsapp_webhook.py list
"""

import argparse
import hashlib
import hmac
import json
import sys
import time
import uuid
from urllib.parse import urlparse

import httpx

# FAKE, local-only. Not your Meta credentials. Set the same values in the API terminal before starting it.
FAKE_APP_SECRET = "FAKE_local_app_secret_not_real"
FAKE_VERIFY_TOKEN = "FAKE_local_verify_token_not_real"
FAKE_PHONE = "256772000111"  # obviously fake Ugandan-format number (digits, no +)
FAKE_PHONE_NUMBER_ID = "000000000000000"
DEFAULT_URL = "http://localhost:8000/api/v1/channels/whatsapp/webhook"
DEFAULT_TEXT = "I need 5 million for stock for my shop"


def _envelope(value: dict) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "0", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "256000000000", "phone_number_id": FAKE_PHONE_NUMBER_ID}, **value}}]}]}


def message_payload(msg: dict, phone: str = FAKE_PHONE) -> dict:
    return _envelope({"contacts": [{"wa_id": phone, "profile": {"name": "Test User"}}],
                      "messages": [{"from": phone, "timestamp": str(int(time.time())), **msg}]})


def status_payload(wamid: str, status: str = "delivered", phone: str = FAKE_PHONE, error_code: int | None = None) -> dict:
    st = {"id": wamid, "status": status, "timestamp": str(int(time.time())), "recipient_id": phone}
    if error_code is not None:
        st["errors"] = [{"code": error_code, "title": "fake error"}]
    return _envelope({"statuses": [st]})


def build(name: str, *, phone: str = FAKE_PHONE, text: str = DEFAULT_TEXT,
          message_id: str | None = None, button_id: str = "confirm", status_for: str = "wamid.FAKE_OUT_1") -> dict:
    mid = message_id or f"wamid.FAKE_{uuid.uuid4().hex[:16]}"
    if name in ("text", "duplicate"):
        return message_payload({"id": mid, "type": "text", "text": {"body": text}}, phone)
    if name == "button":
        return message_payload({"id": mid, "type": "interactive", "interactive": {
            "type": "button_reply", "button_reply": {"id": button_id, "title": "Yes, that's right"}}}, phone)
    if name == "unsupported":  # a voice note: a type WEZA cannot read
        return message_payload({"id": mid, "type": "audio", "audio": {"id": "FAKE_MEDIA", "mime_type": "audio/ogg"}}, phone)
    if name == "image":  # needs a real media id from Meta to be downloaded; against a local fake it fails politely
        return message_payload({"id": mid, "type": "image", "image": {
            "id": "FAKE_MEDIA", "mime_type": "image/jpeg", "caption": text if text != DEFAULT_TEXT else "my payslip"}}, phone)
    if name == "document":
        return message_payload({"id": mid, "type": "document", "document": {
            "id": "FAKE_MEDIA", "mime_type": "application/pdf", "filename": "bank-statement.pdf"}}, phone)
    if name == "status":
        return status_payload(status_for, "delivered", phone)
    if name == "status_failed":
        return status_payload(status_for, "failed", phone, error_code=131026)
    raise KeyError(name)


FIXTURES = ["verify", "text", "button", "duplicate", "unsupported", "image", "document", "status", "status_failed",
            "bad_signature", "no_signature"]


def sign(raw: bytes, secret: str = FAKE_APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _require_local(url: str) -> None:
    if urlparse(url).hostname not in ("localhost", "127.0.0.1", "::1"):
        sys.exit("Refusing: this helper only talks to a local API (localhost / 127.0.0.1).")


def _post(url: str, payload: dict, *, signature: str | None | bool = True) -> httpx.Response:
    raw = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature is True:
        headers["X-Hub-Signature-256"] = sign(raw)
    elif signature:
        headers["X-Hub-Signature-256"] = signature
    return httpx.post(url, content=raw, headers=headers, timeout=30)


def _summary(label: str, r: httpx.Response) -> None:
    code = ""
    try:
        body = r.json()
        code = str((body.get("error") or {}).get("code") or body.get("ok") or "")
    except ValueError:
        pass
    print(f"{label:<14} HTTP {r.status_code}  {code}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fixture", choices=[*FIXTURES, "list"])
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--button", default="confirm", help="button id, e.g. confirm or select:<match_id>")
    ap.add_argument("--phone", default=FAKE_PHONE, help="digits; defaults to a fake number")
    ap.add_argument("--status-for", default="wamid.FAKE_OUT_1", help="provider message id a status refers to")
    a = ap.parse_args()
    if a.fixture == "list":
        print("\n".join(FIXTURES))
        return 0
    _require_local(a.url)
    if a.fixture == "verify":
        ok = httpx.get(a.url, params={"hub.mode": "subscribe", "hub.verify_token": FAKE_VERIFY_TOKEN,
                                      "hub.challenge": "12345"}, timeout=10)
        bad = httpx.get(a.url, params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
                        timeout=10)
        print(f"verify good    HTTP {ok.status_code}  challenge_echoed={ok.text == '12345'}")
        print(f"verify wrong   HTTP {bad.status_code}")
        return 0
    if a.fixture == "bad_signature":
        _summary("bad_signature", _post(a.url, build("text", phone=a.phone, text=a.text), signature="sha256=" + "0" * 64))
        return 0
    if a.fixture == "no_signature":
        _summary("no_signature", _post(a.url, build("text", phone=a.phone, text=a.text), signature=False))
        return 0
    kw = {"phone": a.phone, "text": a.text, "button_id": a.button, "status_for": a.status_for}
    if a.fixture == "duplicate":
        mid = f"wamid.FAKE_{uuid.uuid4().hex[:16]}"
        for i in (1, 2):
            _summary(f"duplicate #{i}", _post(a.url, build("duplicate", message_id=mid, **kw)))
        return 0
    _summary(a.fixture, _post(a.url, build(a.fixture, **kw)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
