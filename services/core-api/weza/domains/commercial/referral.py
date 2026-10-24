"""Partner and campaign links and their QR codes (BRD §5 "Click-to-WhatsApp links and QR codes", FSD §53 "a trackable
link/QR", TSD §73).

A link opens WhatsApp on WEZA's business number with a first message that carries a short acquisition reference,
"(ref:source~campaign~partner~referral)". The WhatsApp inbound code reads and strips it and records the lineage (see
`record_attribution`), so every customer who arrives through a link or a printed QR code can be traced to the campaign
and partner behind it. The format here must stay in sync with `whatsapp_inbound.split_ref` and `apps/web/lib/whatsapp.ts`.
"""

import re
from urllib.parse import quote

import segno

from weza.config import get_settings
from weza.platform.errors import ValidationFailed

CODE = re.compile(r"[A-Za-z0-9_.-]{1,40}")  # no "~": that is the separator
PARTS = (("Source", "source"), ("Campaign", "campaign"), ("Partner", "partner"), ("Referral", "referral"))


def reference(source: str | None = None, campaign: str | None = None, partner: str | None = None,
              referral: str | None = None) -> str:
    """The "(ref:src~cmp~ptn~ref)" tag for a link. Each part is a short marketing code, never personal data."""
    parts = []
    for (label, _), value in zip(PARTS, (source, campaign, partner, referral), strict=True):
        value = (value or "").strip()
        if value and not CODE.fullmatch(value):
            raise ValidationFailed(f"{label} may use letters, numbers, dots, dashes and underscores (up to 40).",
                                   code="INVALID_REFERRAL_CODE")
        parts.append(value)
    if not any(parts):
        raise ValidationFailed("Give at least a source, campaign, partner or referral code.", code="REFERRAL_CODE_REQUIRED")
    return "(ref:" + "~".join(parts) + ")"


def whatsapp_link(source: str | None = None, campaign: str | None = None, partner: str | None = None,
                  referral: str | None = None, text: str = "Hi") -> str:
    number = get_settings().whatsapp_public_number
    if not number:
        raise ValidationFailed("The WhatsApp business number is not configured yet (WHATSAPP_BUSINESS_NUMBER).",
                               code="WHATSAPP_NUMBER_MISSING")
    first_message = ((text or "").strip()[:200] or "Hi") + "\n" + reference(source, campaign, partner, referral)
    return f"https://wa.me/{number}?text={quote(first_message, safe='')}"


def qr_svg(link: str) -> str:
    """The QR code for a link as an inline SVG: scalable, so one file prints crisply on a poster or a business card."""
    return segno.make(link, error="m").svg_inline(scale=8, border=3, dark="#0b1f3a", light="#ffffff",
                                                   omitsize=False, title="WEZA on WhatsApp")
