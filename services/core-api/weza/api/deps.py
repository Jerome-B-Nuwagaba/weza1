"""FastAPI dependencies: database session, authenticated actors, client metadata."""

import uuid
from dataclasses import replace
from urllib.parse import urlsplit

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.customer.models import Customer
from weza.domains.identity import service as identity
from weza.platform.context import Actor
from weza.platform.db import get_db
from weza.platform.errors import Forbidden, Unauthorized

# scope="function": commit before the response is sent, so a client acting on a response never reads ahead of it.
DB = Depends(get_db, scope="function")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")) or ""


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def staff_actor(request: Request, authorization: str | None = Header(None), db: Session = DB) -> Actor:
    token = _bearer(authorization)
    if not token:
        raise Unauthorized("Please sign in.")
    return replace(identity.actor_from_access_token(db, token), ip=client_ip(request)[:64])


def institution_actor(actor: Actor = Depends(staff_actor)) -> Actor:
    if not actor.is_institution:
        raise Forbidden("This area is for institution users.")
    return actor


def weza_actor(actor: Actor = Depends(staff_actor)) -> Actor:
    if not actor.is_weza:
        raise Forbidden("This area is for WEZA staff.")
    return actor


def require_customer_csrf(request: Request) -> None:
    """Only the configured web clients may establish or mutate cookie-backed customer sessions."""
    settings = get_settings()

    def origin(value: str) -> str:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
                return ""
            return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        except ValueError:
            return ""

    allowed = {origin(value.strip()) for value in [settings.public_web_url, *settings.cors_origins.split(",")]}
    allowed.discard("")
    # Browsers omit Origin for same-origin GETs (the magic-link exchange), but send Referer.
    supplied = request.headers.get("origin")
    request_origin = origin(supplied if supplied is not None else request.headers.get("referer", ""))
    if request.headers.get("x-weza-csrf") != "1" or request_origin not in allowed:
        raise Forbidden("Please return to WEZA and try again.", code="CUSTOMER_CSRF_INVALID")


def _customer_token(request: Request, authorization: str | None) -> str | None:
    token = _bearer(authorization)
    if token or authorization:
        return token
    token = request.cookies.get("weza_cs")
    if token and request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_customer_csrf(request)
    return token


def customer_actor(request: Request, authorization: str | None = Header(None), db: Session = DB) -> Actor:
    token = _customer_token(request, authorization)
    if not token or not token.startswith("cs_"):
        raise Unauthorized("Please verify your phone number to continue.", code="CUSTOMER_AUTH_REQUIRED")
    cid = identity.resolve_customer_session(db, token)
    if cid is None:
        raise Unauthorized("Your session has expired. Please verify your phone again.", code="CUSTOMER_AUTH_REQUIRED")
    cust = db.get(Customer, cid)
    if cust is None or cust.status != "ACTIVE":
        raise Unauthorized("Account not active.")
    return Actor(kind="CUSTOMER", id=cid, display="customer", ip=client_ip(request)[:64])


def optional_customer(request: Request, authorization: str | None = Header(None), db: Session = DB) -> uuid.UUID | None:
    token = _customer_token(request, authorization)
    if token and token.startswith("cs_"):
        return identity.resolve_customer_session(db, token)
    return None


def require_step_up(actor: Actor) -> None:
    """Kill switches and vault lookups need an MFA-verified session where MFA is enrolled (blueprint 10 §6)."""
    from weza.config import get_settings
    if get_settings().mfa_enforced and not actor.mfa:
        raise Forbidden("Please sign in with MFA to perform this action.", code="MFA_STEP_UP_REQUIRED")
