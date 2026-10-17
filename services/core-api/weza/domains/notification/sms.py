"""Provider-agnostic SMS adapter slot (real OTP delivery).

`send_customer_message(channel="sms")` asks `resolve()` for a sender. With SMS_PROVIDER unset/console/simulator
(or a REPLACE_ME placeholder) nothing is resolved and the message goes to the simulator inbox, so dev mode keeps
showing the OTP. A real provider is a small class registered under its SMS_PROVIDER name:

    class MyProviderSender:
        def __init__(self, settings): ...
        def send(self, to_e164: str, body: str) -> SendResult: ...

    register_sms_provider("my_provider", MyProviderSender)

SMS_PROVIDER=whatsapp (built in, see the bottom of this file) delivers codes through the Meta WhatsApp Cloud API.
>>> USER INPUT REQUIRED: for a different SMS gateway, name the provider; its sender class is registered here and its
credentials go in services/core-api/.env (SMS_PROVIDER, SMS_API_KEY, SMS_USERNAME, SMS_SENDER_ID).
"""

import re
from collections.abc import Callable
from typing import Protocol

from weza.config import Settings, is_configured
from weza.domains.notification.service import SendResult  # noqa: F401 — re-exported for provider classes


class SmsSender(Protocol):
    def send(self, to_e164: str, body: str) -> SendResult: ...


_PROVIDERS: dict[str, Callable[[Settings], SmsSender]] = {}


def register_sms_provider(name: str, factory: Callable[[Settings], SmsSender]) -> None:
    _PROVIDERS[name.strip().lower()] = factory


def resolve(s: Settings) -> tuple[SmsSender | None, str | None]:
    """→ (sender, None) when usable, else (None, reason): PROVIDER_NOT_IMPLEMENTED | NOT_CONFIGURED."""
    factory = _PROVIDERS.get(s.sms_provider_name)
    if factory is None:
        return None, "PROVIDER_NOT_IMPLEMENTED"
    if not s.sms_ready:
        return None, "NOT_CONFIGURED"
    return factory(s), None


# ------------------------------------------------------------------ SMS_PROVIDER=whatsapp: codes via Meta's Cloud API


class WhatsAppOtpSender:
    """Sends the verification code over the WhatsApp Cloud API (same credentials as the conversation channel).

    With WHATSAPP_OTP_TEMPLATE_NAME set it sends that approved authentication template (works with or without an
    open 24-hour window); otherwise a plain message, which Meta accepts only inside the window (error 131047 otherwise).
    UNVERIFIED AGAINST REAL META until tested with your account."""

    def __init__(self, settings: Settings):
        self.s = settings

    def send(self, to_e164: str, body: str) -> SendResult:
        from weza.domains.notification.service import _graph_post
        to = to_e164.lstrip("+")
        m = re.search(r"\b(\d{4,8})\b", body)
        name = (self.s.whatsapp_otp_template_name or "").strip()
        if is_configured(name) and m:
            code = m.group(1)
            msg = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": {
                "name": name, "language": {"code": self.s.whatsapp_otp_template_language or "en"},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": code}]},
                    {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": code}]}]}}
        else:
            msg = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body[:4096]}}
        return _graph_post(msg)


register_sms_provider("whatsapp", WhatsAppOtpSender)
