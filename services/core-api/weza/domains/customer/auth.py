"""Short-lived, single-use browser handoffs for already verified customers.

Magic credentials share the persisted session store, but have their own prefix and channel and
can never be used directly as a customer session. Only token hashes are stored.
"""

import uuid
from datetime import timedelta
from urllib.parse import urlencode

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.customer.models import Customer
from weza.domains.identity import service as identity
from weza.domains.identity.models import CustomerSession
from weza.platform import crypto
from weza.platform.db import utcnow
from weza.platform.errors import Unauthorized

COOKIE = "weza_cs"
COOKIE_PATH = "/api/v1"
MAGIC_TTL_SECONDS = 600


def issue_magic_link(db: Session, customer_id: uuid.UUID) -> str:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.status != "ACTIVE":
        raise Unauthorized("Account not active.")
    token = "cm_" + crypto.new_token()
    db.add(CustomerSession(customer_id=customer_id, token_hash=crypto.hash_token(token), channel="magic",
                           expires_at=utcnow() + timedelta(seconds=MAGIC_TTL_SECONDS)))
    query = urlencode({"token": token, "next": "/c/requests"})
    return f"{get_settings().public_web_url.rstrip('/')}/start?{query}"


def exchange_magic_token(db: Session, token: str) -> str:
    if not token.startswith("cm_"):
        raise Unauthorized("This sign-in link is invalid or expired. Please verify your phone.", code="MAGIC_INVALID")
    # The conditional update claims the credential atomically even across separate API workers.
    customer_id = db.execute(update(CustomerSession).where(
        CustomerSession.token_hash == crypto.hash_token(token), CustomerSession.channel == "magic",
        CustomerSession.revoked.is_(False), CustomerSession.expires_at > utcnow(),
    ).values(revoked=True).returning(CustomerSession.customer_id)).scalar_one_or_none()
    customer = db.get(Customer, customer_id) if customer_id else None
    if customer is None or customer.status != "ACTIVE":
        raise Unauthorized("This sign-in link is invalid or expired. Please verify your phone.", code="MAGIC_INVALID")
    return identity.create_customer_session(db, customer.id, "web")


def revoke_browser_session(db: Session, token: str | None) -> None:
    if token and token.startswith("cs_"):
        row = db.execute(select(CustomerSession).where(
            CustomerSession.token_hash == crypto.hash_token(token), CustomerSession.channel != "magic",
        ).with_for_update()).scalar_one_or_none()
        if row:
            row.revoked = True


def set_session_cookie(response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.is_production or settings.env not in {"local", "test"},
                        samesite="lax", max_age=settings.customer_session_days * 86400, path=COOKIE_PATH)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
