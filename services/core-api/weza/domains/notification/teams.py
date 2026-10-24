"""Microsoft Teams notifications for institutions (FSD §33, BRD §20, TSD §34).

An institution connects a Teams channel by giving WEZA a webhook URL (Teams "Workflows → post to a channel when a webhook
request is received", or a legacy incoming webhook). WEZA then posts a short card there for the alerts the institution
chose Teams for. The URL is a secret (anyone holding it can post to the channel), so it is stored encrypted and never sent
back to the browser; only whether one is set is. The host must be a Microsoft one, so this cannot be turned into a way to
make WEZA call arbitrary addresses.
"""

import base64
import logging
from urllib.parse import urlparse

import httpx

from weza.config import get_settings
from weza.platform import crypto
from weza.platform.errors import ValidationFailed

log = logging.getLogger("weza.teams")
ALLOWED_HOST_SUFFIXES = (".webhook.office.com", ".logic.azure.com", ".powerplatform.com")
KEY = "teams_webhook_enc"


class TeamsError(Exception):
    pass


def validate_url(url: str) -> str:
    url = (url or "").strip()
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not any(host.endswith(s) for s in ALLOWED_HOST_SUFFIXES) or u.username or u.password:
        raise ValidationFailed("Enter the https webhook address Microsoft Teams gave you (it ends in webhook.office.com, "
                               "logic.azure.com or powerplatform.com).", code="INVALID_TEAMS_URL")
    return url


def set_webhook(profile: dict, url: str | None) -> dict:
    """The institution profile with the webhook stored encrypted (or removed when `url` is empty)."""
    profile = {k: v for k, v in (profile or {}).items() if k != KEY}
    if url:
        ct, wk = crypto.encrypt_bytes(validate_url(url).encode())
        profile[KEY] = base64.b64encode(wk).decode() + "." + base64.b64encode(ct).decode()
    return profile


def webhook(profile: dict | None) -> str | None:
    token = (profile or {}).get(KEY)
    if not token:
        return None
    wk, ct = token.split(".")
    return crypto.decrypt_bytes(base64.b64decode(ct), base64.b64decode(wk)).decode()


def configured(profile: dict | None) -> bool:
    return bool((profile or {}).get(KEY))


def card(title: str, body: str, link: str | None) -> dict:
    """An Adaptive Card message, the format Teams Workflows expect."""
    blocks = [{"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True}]
    if body:
        blocks.append({"type": "TextBlock", "text": body, "wrap": True})
    content = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
               "body": blocks}
    if link:
        content["actions"] = [{"type": "Action.OpenUrl", "title": "Open in WEZA",
                               "url": get_settings().public_web_url.rstrip("/") + link}]
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                                                "content": content}]}


def post(url: str, title: str, body: str = "", link: str | None = None) -> None:
    """Send one card. Raises TeamsError if Teams does not accept it (the notification is then retried or dead-lettered)."""
    try:
        r = httpx.post(validate_url(url), json=card(title, body, link), timeout=10, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise TeamsError(f"Teams could not be reached ({type(exc).__name__})") from exc
    except ValidationFailed as exc:
        raise TeamsError(exc.message) from exc
    if r.status_code >= 300:  # Teams answers 200 or 202 when it has the card
        log.warning("teams_post_rejected", extra={"data": {"status": r.status_code}})
        raise TeamsError(f"Teams refused the message (HTTP {r.status_code})")
