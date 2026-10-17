"""Production service adapters (blueprint 13 go-live): SMS providers, email transport, ClamAV scanning, and the
start-up guard that refuses a production boot without them. Provider HTTP and SMTP are stubbed; clamd is faked."""

import socket
import struct
import threading

import httpx
import pytest
from sqlalchemy import select

from weza.config import Settings
from weza.domains.customer import documents as docs
from weza.domains.misc_models import ChannelMessage
from weza.domains.notification import service as notify
from weza.platform import crypto
from weza.platform.db import session_scope

READY = dict(env="production", secret_key="s" * 40, vault_master_key="k" * 44, blind_index_key="b" * 32,
             mfa_enforced=True, otp_delivery="sms", sms_provider="africastalking", africastalking_username="weza",
             africastalking_api_key="key", malware_scanner="clamav", identity_provider="gnugrid",
             gnugrid_base_url="https://gnugrid.example", gnugrid_api_key="k", gngrid_use_mock=False, smtp_url="smtps://apikey:pw@smtp.example:465",
             cors_origins="https://weza.example")


def test_production_readiness_lists_every_blocker():
    assert Settings(**READY).production_problems() == []
    problems = " | ".join(Settings(env="production").production_problems())
    for expected in ("development secrets", "MFA_ENFORCED", "OTP_DELIVERY", "SMS_PROVIDER", "MALWARE_SCANNER",
                     "SMTP_URL", "IDENTITY_PROVIDER", "GNGRID_USE_MOCK"):
        assert expected in problems
    sandbox = Settings(**{**READY, "africastalking_username": "sandbox"}).production_problems()
    assert any("sandbox" in p for p in sandbox)


def test_api_refuses_to_start_in_production_when_not_ready(monkeypatch):
    import weza.main
    monkeypatch.setattr(weza.main, "get_settings", lambda: Settings(env="production"))
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        weza.main.create_app(start_worker=False)


def _stub_post(monkeypatch, response: httpx.Response) -> list[dict]:
    calls: list[dict] = []

    def fake_post(url, **kw):
        calls.append({"url": url, **kw})
        return response
    monkeypatch.setattr(notify.httpx, "post", fake_post)
    return calls


def test_africastalking_adapter(monkeypatch):
    monkeypatch.setattr(notify, "get_settings", lambda: Settings(**{**READY, "africastalking_sender_id": "WEZA"}))
    calls = _stub_post(monkeypatch, httpx.Response(201, json={"SMSMessageData": {"Recipients": [
        {"number": "+256772000001", "status": "Success", "statusCode": 101}]}}))
    assert notify._africastalking_send("+256772000001", "Hello") is True
    assert calls[0]["url"] == "https://api.africastalking.com/version1/messaging"
    assert calls[0]["headers"]["apiKey"] == "key" and calls[0]["data"]["from"] == "WEZA"
    # A recipient the provider rejects is a failure, not a silent "sent"
    _stub_post(monkeypatch, httpx.Response(201, json={"SMSMessageData": {"Recipients": [
        {"status": "InvalidPhoneNumber", "statusCode": 403}]}}))
    assert notify._africastalking_send("+256772000001", "Hello") is False


def test_twilio_adapter_uses_messaging_service(monkeypatch):
    monkeypatch.setattr(notify, "get_settings", lambda: Settings(**{
        **READY, "sms_provider": "twilio", "twilio_account_sid": "AC1", "twilio_auth_token": "t",
        "twilio_from": "MG123"}))
    calls = _stub_post(monkeypatch, httpx.Response(201, json={"sid": "SM1"}))
    assert notify._twilio_send("+256772000002", "Hi") is True
    assert calls[0]["data"]["MessagingServiceSid"] == "MG123" and calls[0]["auth"] == ("AC1", "t")
    _stub_post(monkeypatch, httpx.Response(400, json={"code": 21211}))
    assert notify._twilio_send("+256772000002", "Hi") is False


def test_real_provider_otp_is_not_stored_and_failures_are_reported(monkeypatch):
    monkeypatch.setattr(notify, "get_settings", lambda: Settings(**READY))
    phone = "+256772999001"
    _stub_post(monkeypatch, httpx.Response(201, json={"SMSMessageData": {"Recipients": [{"statusCode": 101}]}}))
    with session_scope() as db:
        assert notify.send_customer_message(db, phone, "Your WEZA verification code is 123456.", kind="otp")
    _stub_post(monkeypatch, httpx.Response(500))
    with session_scope() as db:
        assert not notify.send_customer_message(db, phone, "Update on your request", kind="info")
    with session_scope() as db:
        rows = db.execute(select(ChannelMessage).where(
            ChannelMessage.to_index == crypto.blind_index("phone", phone)).order_by(ChannelMessage.created_at)).scalars().all()
        assert [(m.provider, m.status) for m in rows] == [("africastalking", "SENT"), ("africastalking", "FAILED")]
        assert "123456" not in rows[0].body


class _FakeClamd:
    """Minimal clamd INSTREAM server: replies FOUND when the stream contains the marker."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                buf = b""
                while b"\0" not in buf:
                    buf += conn.recv(64)
                cmd, rest = buf.split(b"\0", 1)
                assert cmd == b"zINSTREAM"
                body = rest
                data = b""
                while True:
                    while len(body) < 4:
                        body += conn.recv(65536)
                    (n,) = struct.unpack(">I", body[:4])
                    body = body[4:]
                    if n == 0:
                        break
                    while len(body) < n:
                        body += conn.recv(65536)
                    data, body = data + body[:n], body[n:]
                conn.sendall(b"stream: Test.Marker FOUND\0" if b"MARKER" in data else b"stream: OK\0")

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)  # unblocks accept() on Linux, where close() alone does not
        except OSError:
            pass
        self.sock.close()


def _unused_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # never listened on, so connections are refused
    return port


def test_clamav_scanner():
    clamd = _FakeClamd()
    try:
        scanner = docs.ClamAVScanner("127.0.0.1", clamd.port, 5)
        big = b"%PDF-1.4\n" + b"x" * 200_000  # several INSTREAM chunks
        assert scanner.scan(big) == (True, "clean")
        ok, result = scanner.scan(b"%PDF-1.4\nMARKER")
        assert not ok and result == "malware_signature:Test.Marker"
    finally:
        clamd.close()
    # Fail closed when clamd is unreachable
    assert docs.ClamAVScanner("127.0.0.1", _unused_port(), 1).scan(b"%PDF-1.4\n") == (False, docs.SCAN_UNAVAILABLE)


@pytest.mark.parametrize(("url", "ssl"), [("smtps://apikey:p%40ss@smtp.example:465", True),
                                          ("smtp://user%40weza.africa:pw@smtp.example", False)])
def test_email_transport(monkeypatch, url, ssl):
    sent: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.update(host=host, port=port, ssl=self.SSL)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["starttls"] = True

        def login(self, user, pw):
            sent["login"] = (user, pw)

        def send_message(self, msg):
            sent["from"], sent["to"] = msg["From"], msg["To"]

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", type("S", (FakeSMTP,), {"SSL": False}))
    monkeypatch.setattr(smtplib, "SMTP_SSL", type("S", (FakeSMTP,), {"SSL": True}))
    smtp_from = "WEZA <alerts@weza.africa>" if ssl else None
    monkeypatch.setattr(notify, "get_settings", lambda: Settings(smtp_url=url, smtp_from=smtp_from))
    notify._send_email("officer@bank.example", "Subject", "Body")
    assert sent["ssl"] is ssl and sent["port"] == (465 if ssl else 587) and sent.get("starttls", False) is not ssl
    assert sent["to"] == "officer@bank.example"
    if ssl:
        assert sent["login"] == ("apikey", "p@ss") and sent["from"] == "WEZA <alerts@weza.africa>"
    else:
        assert sent["from"] == "user@weza.africa"
