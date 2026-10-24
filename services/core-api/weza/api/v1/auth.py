"""Staff authentication: password + TOTP MFA, rotating refresh tokens in an httpOnly cookie (TSD §13)."""

from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from weza.api.deps import DB, client_ip, staff_actor
from weza.config import get_settings
from weza.domains.identity import entra
from weza.domains.identity import service as identity
from weza.domains.identity.models import User
from weza.domains.trust.policy import ROLE_LABELS, permissions_for
from weza.platform.context import Actor
from weza.platform.errors import Unauthorized, WezaError

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "weza_rt"
ENTRA_COOKIE = "weza_entra"


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


@router.get("/entra/config")
def entra_config():
    """Whether the login page should offer 'Sign in with Microsoft'."""
    return {"enabled": entra.enabled()}


@router.get("/entra/start")
def entra_start(next: str | None = None):  # noqa: A002 — the query parameter is named `next`
    url, state = entra.begin(next)
    redirect = RedirectResponse(url, status_code=302)
    s = get_settings()
    redirect.set_cookie(ENTRA_COOKIE, state, httponly=True, secure=s.is_production or s.env != "local", samesite="lax",
                        max_age=600, path="/api/v1/auth/entra")
    return redirect


@router.get("/entra/callback")
def entra_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                   weza_entra: str | None = Cookie(None), db: Session = DB):
    """Microsoft sends the browser back here. Every outcome is a redirect to the login page, never a JSON error."""
    web = get_settings().public_web_url.rstrip("/")

    def fail(code_: str) -> RedirectResponse:
        out = RedirectResponse(f"{web}/login?{urlencode({'sso_error': code_})}", status_code=302)
        out.delete_cookie(ENTRA_COOKIE, path="/api/v1/auth/entra")
        return out
    if error or not code or not state:
        return fail("ENTRA_CANCELLED")
    try:
        result, next_path = entra.complete(db, code, state, weza_entra, client_ip(request))
    except WezaError as exc:
        db.commit()  # a recorded denial must survive
        return fail(exc.code)
    params = {"next": next_path} if next_path else {}
    if "mfa_token" in result:  # Microsoft did not perform MFA and WEZA still requires it: continue on the login page
        params.update(sso_mfa=result["mfa_token"], enrol="1" if result.get("mfa_enrolment_required") else "0")
    else:
        params["sso"] = "1"
    out = RedirectResponse(f"{web}/login?{urlencode(params)}", status_code=302)
    if "refresh_token" in result:
        _set_cookie(out, result["refresh_token"])
    out.delete_cookie(ENTRA_COOKIE, path="/api/v1/auth/entra")
    return out


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
