"""Identity Vault, phone OTP, customer sessions, staff authentication with TOTP MFA (TSD §12–13)."""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.identity.models import (
    CustomerSession,
    Membership,
    OtpChallenge,
    RefreshToken,
    User,
    VaultRecord,
)
from weza.domains.trust import policy
from weza.domains.trust import roles as canon
from weza.domains.trust.service import audit
from weza.platform import crypto
from weza.platform.context import SYSTEM, Actor
from weza.platform.controls import rate_limit
from weza.platform.db import utcnow
from weza.platform.errors import Conflict, Forbidden, Unauthorized, ValidationFailed

# ------------------------------------------------------------------ vault


def vault_find_by_phone(db: Session, phone_e164: str) -> VaultRecord | None:
    return db.execute(select(VaultRecord).where(VaultRecord.phone_index == crypto.blind_index("phone", phone_e164))
                      ).scalar_one_or_none()


def vault_create(db: Session, phone_e164: str) -> VaultRecord:
    ct, wk = crypto.encrypt_record({"phone": phone_e164})
    rec = VaultRecord(phone_index=crypto.blind_index("phone", phone_e164), ciphertext=ct, wrapped_key=wk,
                      phone_last4=phone_e164[-3:])
    db.add(rec)
    db.flush()
    return rec


def vault_read(db: Session, token: uuid.UUID) -> dict:
    rec = db.get(VaultRecord, token)
    if rec is None:
        return {}
    return crypto.decrypt_record(rec.ciphertext, rec.wrapped_key)


def vault_update(db: Session, token: uuid.UUID, **fields) -> None:
    rec = db.get(VaultRecord, token)
    if rec is None:
        return
    data = crypto.decrypt_record(rec.ciphertext, rec.wrapped_key)
    data.update({k: v for k, v in fields.items() if v is not None})
    rec.ciphertext, rec.wrapped_key = crypto.encrypt_record(data)
    if fields.get("nin"):
        rec.nin_index = crypto.blind_index("nin", fields["nin"])


def mask_phone(phone: str | None) -> str:
    if not phone or len(phone) < 7:
        return "•••"
    return f"{phone[:4]} {phone[4]}•• ••• {phone[-3:]}"


# ------------------------------------------------------------------ OTP (FSD-IDV-001)


class OtpResult:
    def __init__(self, ok: bool, code: str, message: str, challenge: OtpChallenge | None = None,
                 dev_code: str | None = None):
        self.ok, self.code, self.message, self.challenge, self.dev_code = ok, code, message, challenge, dev_code


def issue_otp(db: Session, phone_e164: str, *, ip: str = "", journey_id: uuid.UUID | None = None,
              channel: str = "sms", deliver_via: str = "sms") -> OtpResult:
    """`deliver_via`: "sms" (default) or "whatsapp" — the latter only for the number the customer is chatting from."""
    s = get_settings()
    idx = crypto.blind_index("phone", phone_e164)
    rate_limit(db, f"otp:phone:{idx}", 5, 900, "Too many codes requested for this number. Try again in 15 minutes.")
    if ip:
        rate_limit(db, f"otp:ip:{crypto.sha256_hex(ip)}", 20, 900)
    now = utcnow()
    existing = db.execute(select(OtpChallenge).where(OtpChallenge.phone_index == idx, OtpChallenge.status == "PENDING")
                          .order_by(OtpChallenge.created_at.desc()).limit(1)).scalar_one_or_none()
    if existing and existing.expires_at > now:
        if (now - existing.last_sent_at).total_seconds() < s.otp_resend_cooldown_seconds:
            return OtpResult(False, "OTP_COOLDOWN", "Please wait a few seconds before requesting another code.", existing)
        if existing.resend_count >= s.otp_max_resends:
            return OtpResult(False, "OTP_RESEND_LIMIT", "You've requested the maximum number of codes. "
                             "Please try again in 15 minutes.", existing)
        existing.status = "EXPIRED"
        resends = existing.resend_count + 1
    else:
        resends = 0
    code = crypto.generate_otp()
    salt = crypto.new_salt()
    ch = OtpChallenge(phone_index=idx, code_hash=crypto.hash_otp(code, salt), salt=salt,
                      expires_at=now + timedelta(seconds=s.otp_ttl_seconds), resend_count=resends, last_sent_at=now,
                      channel=channel, journey_id=journey_id)
    db.add(ch)
    db.flush()
    from weza.domains.notification.service import send_customer_message
    delivered = send_customer_message(db, phone_e164, f"Your WEZA verification code is {code}. It expires in 5 "
                                      "minutes. Never share this code.", channel=deliver_via, kind="otp")
    if not delivered:
        ch.status = "FAILED_DELIVERY"
        return OtpResult(False, "OTP_DELIVERY_FAILED", "We couldn't send the code. Please check the number or try "
                         "again.", ch)
    dev_code = code if (s.otp_delivery == "display" and not s.is_production) else None
    return OtpResult(True, "OTP_SENT", f"We sent a 6-digit code to {mask_phone(phone_e164)}.", ch, dev_code)


def verify_otp(db: Session, challenge_id: uuid.UUID, code: str) -> OtpResult:
    s = get_settings()
    ch = db.execute(select(OtpChallenge).where(OtpChallenge.id == challenge_id).with_for_update()).scalar_one_or_none()
    if ch is None:
        return OtpResult(False, "OTP_NOT_FOUND", "Please request a new code.")
    now = utcnow()
    if ch.status == "LOCKED":
        return OtpResult(False, "OTP_LOCKED", "Too many incorrect attempts. Please request a new code in 15 minutes.", ch)
    if ch.status != "PENDING":
        return OtpResult(False, "OTP_EXPIRED", "This code is no longer valid. Please request a new one.", ch)
    if ch.expires_at <= now:
        ch.status = "EXPIRED"
        return OtpResult(False, "OTP_EXPIRED", "This code has expired. Please request a new one.", ch)
    code = (code or "").strip().replace(" ", "")
    if not crypto.hmac_equal(crypto.hash_otp(code, ch.salt), ch.code_hash):
        ch.attempts += 1
        if ch.attempts >= s.otp_max_attempts:
            ch.status = "LOCKED"
            return OtpResult(False, "OTP_LOCKED", "Too many incorrect attempts. Please request a new code in 15 "
                             "minutes.", ch)
        left = s.otp_max_attempts - ch.attempts
        return OtpResult(False, "OTP_INCORRECT", f"That code is incorrect. {left} attempt{'s' if left != 1 else ''} "
                         "left.", ch)
    ch.status = "VERIFIED"
    return OtpResult(True, "OTP_VERIFIED", "Phone verified.", ch)


# ------------------------------------------------------------------ customer sessions


def create_customer_session(db: Session, customer_id: uuid.UUID, channel: str = "web") -> str:
    token = "cs_" + crypto.new_token()
    db.add(CustomerSession(customer_id=customer_id, token_hash=crypto.hash_token(token), channel=channel,
                           expires_at=utcnow() + timedelta(days=get_settings().customer_session_days)))
    return token


def resolve_customer_session(db: Session, token: str) -> uuid.UUID | None:
    if not token.startswith("cs_"):
        return None
    row = db.execute(select(CustomerSession).where(CustomerSession.token_hash == crypto.hash_token(token))
                     ).scalar_one_or_none()
    if row is None or row.channel == "magic" or row.revoked or row.expires_at <= utcnow():
        return None
    return row.customer_id


# ------------------------------------------------------------------ staff users


def create_user(db: Session, *, email: str, full_name: str, password: str, kind: str,
                institution_id: uuid.UUID | None = None, roles: list[str] | None = None,
                team_id: uuid.UUID | None = None, weza_roles: list[str] | None = None) -> User:
    email = email.strip().lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise Conflict("A user with this email already exists.", code="USER_EXISTS")
    if len(password) < 12:
        raise ValidationFailed("Password must be at least 12 characters.")
    roles = _known_roles(roles, kind)
    weza_roles = _known_roles(weza_roles, kind)
    u = User(email=email, full_name=full_name, password_hash=crypto.hash_password(password), kind=kind,
             weza_roles=weza_roles or [])
    db.add(u)
    db.flush()
    if kind == "INSTITUTION":
        assert institution_id is not None
        db.add(Membership(user_id=u.id, institution_id=institution_id, roles=roles or ["OFFICER"], team_id=team_id))
    return u


def _known_roles(roles: list[str] | None, kind: str) -> list[str]:
    """Reject roles outside the vocabulary for this kind of user, so a typo never silently grants nothing."""
    if not roles:
        return []
    allowed = set(policy.INST_ROLES) if kind == "INSTITUTION" else set(policy.WEZA_ROLES)
    unknown = [r for r in roles if r not in allowed]
    if unknown:
        raise ValidationFailed("Unknown role.", code="UNKNOWN_ROLE", details=[{"role": r} for r in unknown])
    return list(dict.fromkeys(roles))


def _membership(db: Session, user_id: uuid.UUID) -> Membership | None:
    return db.execute(select(Membership).where(Membership.user_id == user_id)).scalar_one_or_none()


def actor_for_user(db: Session, user: User, mfa: bool) -> Actor:
    # Roles are expanded to the canonical vocabulary here, once, so every downstream check reads the
    # same set whatever spelling the institution's administrator chose.
    if user.kind == "WEZA":
        return Actor(kind="WEZA_USER", id=user.id, roles=canon.expand(user.weza_roles), mfa=mfa, display=user.full_name)
    m = _membership(db, user.id)
    if m is None:
        raise Forbidden("Your account is not linked to an institution.")
    return Actor(kind="INSTITUTION_USER", id=user.id, institution_id=m.institution_id, roles=canon.expand(m.roles),
                 team_id=m.team_id, mfa=mfa, display=user.full_name)


def mfa_required(user: User) -> bool:
    """With MFA_ENFORCED every staff login (WEZA and institution) needs a second factor; otherwise only users
    who chose to enrol are asked for one."""
    return user.mfa_enrolled or get_settings().mfa_enforced


def login(db: Session, email: str, password: str, ip: str = "") -> dict:
    email = email.strip().lower()
    rate_limit(db, f"login:email:{crypto.sha256_hex(email)}", 10, 900, "Too many sign-in attempts. Try again later.")
    if ip:
        rate_limit(db, f"login:ip:{crypto.sha256_hex(ip)}", get_settings().login_ip_limit, 900)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or user.status != "ACTIVE":
        crypto.verify_password(password, crypto.hash_password("timing-equaliser-xx"))
        raise Unauthorized("Email or password is incorrect.", code="INVALID_CREDENTIALS")
    if user.locked_until and user.locked_until > utcnow():
        raise Unauthorized("Account temporarily locked after failed attempts. Try again in 15 minutes.",
                           code="ACCOUNT_LOCKED")
    if not crypto.verify_password(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= 5:
            user.locked_until = utcnow() + timedelta(minutes=15)
            user.failed_logins = 0
        audit(db, Actor(kind="ANONYMOUS", display=email, ip=ip[:64]), "auth.login_failed", "user", user.id,
              institution_id=None)
        db.commit()  # failure counters & audit must survive the error response's rollback
        raise Unauthorized("Email or password is incorrect.", code="INVALID_CREDENTIALS")
    user.failed_logins = 0
    if mfa_required(user):
        mfa_token = crypto.sign_jwt({"sub": str(user.id), "typ": "mfa", "token_version": user.token_version}, 10)
        if not user.mfa_enrolled:
            return {"mfa_enrolment_required": True, "mfa_token": mfa_token}
        return {"mfa_required": True, "mfa_token": mfa_token}
    return _issue_tokens(db, user, mfa=False)


def _issue_tokens(db: Session, user: User, mfa: bool, family: uuid.UUID | None = None) -> dict:
    actor = actor_for_user(db, user, mfa)
    claims = {"sub": str(user.id), "typ": "access", "kind": user.kind, "mfa": mfa,
              "token_version": user.token_version}
    access = crypto.sign_jwt(claims, get_settings().access_token_minutes)
    refresh = "rt_" + crypto.new_token()
    db.add(RefreshToken(user_id=user.id, token_hash=crypto.hash_token(refresh), family=family or uuid.uuid4(),
                        expires_at=utcnow() + timedelta(days=get_settings().refresh_token_days), mfa=mfa))
    user.last_login_at = utcnow()
    audit(db, actor, "auth.login", "user", user.id)
    return {"access_token": access, "refresh_token": refresh, "user": user_summary(db, user, actor)}


def user_summary(db: Session, user: User, actor: Actor) -> dict:
    from weza.domains.institution.models import Institution
    inst = db.get(Institution, actor.institution_id) if actor.institution_id else None
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "kind": user.kind,
            "roles": sorted(actor.roles), "institution": ({"id": str(inst.id), "name": inst.display_name,
                                                            "status": inst.status} if inst else None),
            "team_id": str(actor.team_id) if actor.team_id else None, "mfa_enrolled": user.mfa_enrolled,
            "mfa": actor.mfa}


def _user_from_mfa_token(db: Session, token: str) -> User:
    try:
        claims = crypto.verify_jwt(token)
    except Exception as exc:  # noqa: BLE001
        raise Unauthorized("Your sign-in session expired. Please sign in again.") from exc
    if claims.get("typ") != "mfa":
        raise Unauthorized("Invalid MFA token.")
    try:
        user = db.get(User, uuid.UUID(claims["sub"]))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise Unauthorized("Invalid MFA token.") from exc
    if user is None or user.status != "ACTIVE":
        raise Unauthorized("Invalid MFA token.")
    _check_token_version(user, claims)
    return user


def mfa_verify(db: Session, mfa_token: str, code: str) -> dict:
    user = _user_from_mfa_token(db, mfa_token)
    rate_limit(db, f"mfa:{user.id}", 10, 900)
    secret = crypto.decrypt_bytes(user.mfa_secret_ct, user.mfa_secret_key).decode() if user.mfa_secret_ct else None
    if not secret or not crypto.totp_verify(secret, code):
        raise Unauthorized("That code is incorrect.", code="MFA_INVALID")
    return _issue_tokens(db, user, mfa=True)


def mfa_begin_enrolment(db: Session, user: User, existing_mfa_code: str | None = None) -> dict:
    # Password-only login challenges must never replace an already configured second factor.
    if user.mfa_secret_ct:
        rate_limit(db, f"mfa:{user.id}", 10, 900)
        secret = crypto.decrypt_bytes(user.mfa_secret_ct, user.mfa_secret_key).decode()
        if not existing_mfa_code or not crypto.totp_verify(secret, existing_mfa_code):
            raise Unauthorized("Verify your current authenticator code before replacing it.", code="MFA_REQUIRED")
    secret = crypto.totp_new_secret()
    user.mfa_secret_ct, user.mfa_secret_key = crypto.encrypt_bytes(secret.encode())
    user.mfa_enrolled = False
    return {"secret": secret, "otpauth_uri": crypto.totp_uri(secret, user.email)}


def mfa_confirm_enrolment(db: Session, user: User, code: str) -> None:
    secret = crypto.decrypt_bytes(user.mfa_secret_ct, user.mfa_secret_key).decode() if user.mfa_secret_ct else None
    if not secret or not crypto.totp_verify(secret, code):
        raise ValidationFailed("That code is incorrect. Check your authenticator app's time.", code="MFA_INVALID")
    user.mfa_enrolled = True
    audit(db, SYSTEM, "auth.mfa_enrolled", "user", user.id)


def refresh(db: Session, token: str) -> dict:
    row = db.execute(select(RefreshToken).where(RefreshToken.token_hash == crypto.hash_token(token)).with_for_update()
                     ).scalar_one_or_none()
    if row is None or row.revoked or row.expires_at <= utcnow():
        raise Unauthorized("Session expired. Please sign in again.")
    if row.used:
        # Reuse detection: revoke the whole family.
        for r in db.execute(select(RefreshToken).where(RefreshToken.family == row.family)).scalars():
            r.revoked = True
        db.commit()  # Persist revocation before the request dependency rolls back the error response.
        raise Unauthorized("Session expired. Please sign in again.", code="REFRESH_REUSED")
    row.used = True
    user = db.get(User, row.user_id)
    if user is None or user.status != "ACTIVE":
        raise Unauthorized("Session expired. Please sign in again.")
    return _issue_tokens(db, user, mfa=row.mfa, family=row.family)


def set_password(db: Session, user: User, new_password: str) -> None:
    """Replace a staff password and invalidate access, pending MFA and refresh tokens."""
    if len(new_password) < 12:
        raise ValidationFailed("Password must be at least 12 characters.", code="WEAK_PASSWORD")
    if crypto.verify_password(new_password, user.password_hash):
        raise ValidationFailed("Choose a password you haven't used here.", code="PASSWORD_REUSED")
    user.password_hash = crypto.hash_password(new_password)
    user.token_version += 1
    user.failed_logins, user.locked_until = 0, None
    for r in db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id,
                                                   RefreshToken.revoked.is_(False))).scalars():
        r.revoked = True


def logout(db: Session, token: str) -> None:
    row = db.execute(select(RefreshToken).where(RefreshToken.token_hash == crypto.hash_token(token))).scalar_one_or_none()
    if row:
        for r in db.execute(select(RefreshToken).where(RefreshToken.family == row.family)).scalars():
            r.revoked = True


def _check_token_version(user: User, claims: dict) -> None:
    # Tokens minted before this migration belong to the initial version only.
    version = claims.get("token_version", 1)
    if type(version) is not int or version != user.token_version:
        raise Unauthorized("Your session has expired. Please sign in again.", code="TOKEN_EXPIRED")


def actor_from_access_token(db: Session, token: str) -> Actor:
    try:
        claims = crypto.verify_jwt(token)
    except Exception as exc:  # noqa: BLE001
        raise Unauthorized("Your session has expired. Please sign in again.", code="TOKEN_EXPIRED") from exc
    if claims.get("typ") != "access":
        raise Unauthorized("Invalid token.")
    try:
        user = db.get(User, uuid.UUID(claims["sub"]))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise Unauthorized("Invalid token.") from exc
    if user is None or user.status != "ACTIVE":
        raise Unauthorized("Account not active.")
    _check_token_version(user, claims)
    return actor_for_user(db, user, bool(claims.get("mfa")))
