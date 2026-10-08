"""Identity domain: Identity Vault (TSD §12), OTP (TSD §13), customer sessions, staff users and memberships."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin

S = {"schema": "identity"}


class VaultRecord(IdMixin, TimestampMixin, Base):
    """Direct identifiers, encrypted. `id` is the opaque vault token used by every other domain."""

    __tablename__ = "vault_record"
    __table_args__ = (S,)

    phone_index: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nin_index: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    phone_last4: Mapped[str] = mapped_column(String(4), default="")


class OtpChallenge(IdMixin, TimestampMixin, Base):
    __tablename__ = "otp_challenge"
    __table_args__ = (S,)

    phone_index: Mapped[str] = mapped_column(String(64), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    salt: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    resend_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING|VERIFIED|EXPIRED|LOCKED|FAILED_DELIVERY
    channel: Mapped[str] = mapped_column(String(16), default="sms")
    journey_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class CustomerSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "customer_session"
    __table_args__ = (S,)

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    channel: Mapped[str] = mapped_column(String(16), default="web")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class User(IdMixin, TimestampMixin, Base):
    """Institution or WEZA staff user."""

    __tablename__ = "user"
    __table_args__ = (S,)

    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))  # INSTITUTION | WEZA
    weza_roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    mfa_secret_ct: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mfa_secret_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # INVITED|ACTIVE|DISABLED
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)


class Membership(IdMixin, TimestampMixin, Base):
    __tablename__ = "membership"
    __table_args__ = (S,)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("identity.user.id"), unique=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class RefreshToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "refresh_token"
    __table_args__ = (S,)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa: Mapped[bool] = mapped_column(Boolean, default=False)
