"""FastAPI dependencies: database session, authenticated actors, client metadata."""

import uuid

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from weza.domains.customer.models import Customer
from weza.domains.identity import service as identity
from weza.platform.context import Actor
from weza.platform.db import get_db
from weza.platform.errors import Forbidden, Unauthorized

DB = Depends(get_db)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")) or ""


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def staff_actor(authorization: str | None = Header(None), db: Session = DB) -> Actor:
    token = _bearer(authorization)
    if not token:
        raise Unauthorized("Please sign in.")
    return identity.actor_from_access_token(db, token)


def institution_actor(actor: Actor = Depends(staff_actor)) -> Actor:
    if not actor.is_institution:
        raise Forbidden("This area is for institution users.")
    return actor


def weza_actor(actor: Actor = Depends(staff_actor)) -> Actor:
    if not actor.is_weza:
        raise Forbidden("This area is for WEZA staff.")
    return actor


def customer_actor(authorization: str | None = Header(None), db: Session = DB) -> Actor:
    token = _bearer(authorization)
    if not token or not token.startswith("cs_"):
        raise Unauthorized("Please verify your phone number to continue.", code="CUSTOMER_AUTH_REQUIRED")
    cid = identity.resolve_customer_session(db, token)
    if cid is None:
        raise Unauthorized("Your session has expired. Please verify your phone again.", code="CUSTOMER_AUTH_REQUIRED")
    cust = db.get(Customer, cid)
    if cust is None or cust.status != "ACTIVE":
        raise Unauthorized("Account not active.")
    return Actor(kind="CUSTOMER", id=cid, display="customer")


def optional_customer(authorization: str | None = Header(None), db: Session = DB) -> uuid.UUID | None:
    token = _bearer(authorization)
    if token and token.startswith("cs_"):
        return identity.resolve_customer_session(db, token)
    return None


def require_step_up(actor: Actor) -> None:
    """Kill switches and vault lookups need an MFA-verified session where MFA is enrolled (blueprint 10 §6)."""
    from weza.config import get_settings
    if get_settings().mfa_enforced and not actor.mfa:
        raise Forbidden("Please sign in with MFA to perform this action.", code="MFA_STEP_UP_REQUIRED")
