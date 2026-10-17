"""WhatsApp media download (Cloud API): media id → short-lived URL → bytes. Never logs ids, URLs or content.

The downloaded bytes are untrusted: callers must pass them through the document pipeline (quarantine → scan →
magic-byte validation → encrypted storage) before anything else touches them."""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from weza.config import get_settings
from weza.domains.customer.documents import MAX_BYTES
from weza.domains.notification.service import http_get


class MediaError(Exception):
    """Download failed. `code` is a safe short name (no ids, urls or content)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class MediaFile:
    data: bytes
    mime: str


def _safe_url(url: str) -> bool:
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        return False
    try:
        ipaddress.ip_address(u.hostname)
        return False  # raw IPs (incl. localhost/private ranges) are never legitimate Meta media hosts
    except ValueError:
        return u.hostname != "localhost"


def fetch(media_id: str) -> MediaFile:
    s = get_settings()
    if not s.whatsapp_send_ready:
        raise MediaError("NOT_CONFIGURED")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", media_id or ""):
        raise MediaError("BAD_ID")  # the id goes into a URL path
    headers = {"Authorization": f"Bearer {s.whatsapp_token}"}
    try:
        meta = http_get(f"https://graph.facebook.com/{s.graph_api_version}/{media_id}", headers, 15)
        if meta.status_code >= 300:
            raise MediaError(f"META_{meta.status_code}")
        info = meta.json()
        url, size = info.get("url", ""), int(info.get("file_size") or 0)
        if not _safe_url(url):
            raise MediaError("UNSAFE_URL")
        if size > MAX_BYTES:
            raise MediaError("TOO_LARGE")
        r = http_get(url, headers, 30)
    except (httpx.HTTPError, ValueError) as exc:
        raise MediaError("NETWORK") from exc
    if r.status_code >= 300:
        raise MediaError(f"DOWNLOAD_{r.status_code}")
    if len(r.content) > MAX_BYTES:
        raise MediaError("TOO_LARGE")
    return MediaFile(r.content, str(info.get("mime_type") or ""))
