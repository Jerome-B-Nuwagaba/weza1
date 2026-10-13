"""Provider-agnostic SMS adapter slot (real OTP delivery).

`send_customer_message(channel="sms")` asks `resolve()` for a sender. With SMS_PROVIDER unset/console/simulator
(or a REPLACE_ME placeholder) nothing is resolved and the message goes to the simulator inbox, so dev mode keeps
showing the OTP. A real provider is a small class registered under its SMS_PROVIDER name:

    class MyProviderSender:
        def __init__(self, settings): ...
        def send(self, to_e164: str, body: str) -> SendResult: ...

    register_sms_provider("my_provider", MyProviderSender)

>>> USER INPUT REQUIRED: choose your SMS provider and tell the developer its name; its sender class is added and
registered at the bottom of this file, and its credentials go in services/core-api/.env (SMS_PROVIDER, SMS_API_KEY,
SMS_USERNAME, SMS_SENDER_ID). Until then no real SMS is sent and nothing here talks to a provider.
"""

from collections.abc import Callable
from typing import Protocol

from weza.config import Settings
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
