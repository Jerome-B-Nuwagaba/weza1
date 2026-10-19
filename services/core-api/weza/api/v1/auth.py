"""Staff authentication: password + TOTP MFA, rotating refresh tokens in an httpOnly cookie (TSD §13)."""

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from weza.api.deps import DB, client_ip, staff_actor
from weza.config import get_settings
from weza.domains.identity import service as identity
from weza.domains.identity.models import User
from weza.domains.trust.policy import ROLE_LABELS, permissions_for
from weza.platform.context import Actor
from weza.platform.errors import Unauthorized

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "weza_rt"


def _set_cookie(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie(COOKIE, token, httponly=True, secure=s.is_production or s.env != "local", samesite="lax",
                    max_age=s.refresh_token_days * 86400, path="/api/v1/auth")


def _finish(resp: Response, result: dict) -> dict:
    if "refresh_token" in result:
        _set_cookie(resp, result["refresh_token"])
        u = result["user"]
        u["permissions"] = permissions_for(set(u["roles"]))
        u["role_labels"] = {r: ROLE_LABELS.get(r, r) for r in u["roles"]}
    return result


class LoginIn(BaseModel):
    email: str = Field(..., max_length=200)
    password: str = Field(..., max_length=200)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = DB):
    return _finish(response, identity.login(db, body.email, body.password, client_ip(request)))


class MfaIn(BaseModel):
    mfa_token: str
    code: str = Field(..., min_length=6, max_length=8)


@router.post("/mfa/verify")
def mfa_verify(body: MfaIn, response: Response, db: Session = DB):
    return _finish(response, identity.mfa_verify(db, body.mfa_token, body.code))


class RefreshIn(BaseModel):
    refresh_token: str | None = None


@router.post("/refresh")
def refresh(response: Response, body: RefreshIn | None = None, weza_rt: str | None = Cookie(None), db: Session = DB):
    token = (body.refresh_token if body else None) or weza_rt
    if not token:
        raise Unauthorized("Please sign in.")
    return _finish(response, identity.refresh(db, token))


@router.post("/logout")
def logout(response: Response, weza_rt: str | None = Cookie(None), db: Session = DB):
    if weza_rt:
        identity.logout(db, weza_rt)
    response.delete_cookie(COOKIE, path="/api/v1/auth")
    return {"ok": True}


@router.get("/me")
def me(actor: Actor = Depends(staff_actor), db: Session = DB):
    user = db.get(User, actor.id)
    s = identity.user_summary(db, user, actor)
    s["permissions"] = permissions_for(actor.roles)
    s["role_labels"] = {r: ROLE_LABELS.get(r, r) for r in actor.roles}
    from weza.consumers import unread_count
    s["unread_notifications"] = unread_count(db, actor.id)
    return s


class MfaEnrolBeginIn(BaseModel):
    existing_mfa_code: str | None = Field(None, min_length=6, max_length=8)


@router.post("/mfa/enrol")
def mfa_enrol(body: MfaEnrolBeginIn | None = None, actor: Actor = Depends(staff_actor), db: Session = DB):
    return identity.mfa_begin_enrolment(db, db.get(User, actor.id), body.existing_mfa_code if body else None)


class MfaEnrolIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


@router.post("/mfa/enrol/confirm")
def mfa_enrol_confirm(body: MfaEnrolIn, actor: Actor = Depends(staff_actor), db: Session = DB):
    identity.mfa_confirm_enrolment(db, db.get(User, actor.id), body.code)
    return {"ok": True}


class MfaEnrolWithToken(BaseModel):
    mfa_token: str
    existing_mfa_code: str | None = Field(None, min_length=6, max_length=8)


@router.post("/mfa/enrol-pending")
def mfa_enrol_pending(body: MfaEnrolWithToken, db: Session = DB):
    """First-time enrolment during login when MFA is enforced."""
    user = identity._user_from_mfa_token(db, body.mfa_token)
    return identity.mfa_begin_enrolment(db, user, body.existing_mfa_code)


class MfaEnrolPendingConfirm(BaseModel):
    mfa_token: str
    code: str


@router.post("/mfa/enrol-pending/confirm")
def mfa_enrol_pending_confirm(body: MfaEnrolPendingConfirm, response: Response, db: Session = DB):
    user = identity._user_from_mfa_token(db, body.mfa_token)
    identity.mfa_confirm_enrolment(db, user, body.code)
    return _finish(response, identity._issue_tokens(db, user, mfa=True))
