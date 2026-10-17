"""Consent as a bounded domain (TSD §27; FSD §13)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin, utcnow

S = {"schema": "consent"}


class ConsentTemplate(IdMixin, Base):
    """Published consent text. Immutable once published; never altered by AI translation (TSD §72)."""

    __tablename__ = "consent_template"
    __table_args__ = (UniqueConstraint("country_code", "purpose", "version", "language"), S)

    country_code: Mapped[str] = mapped_column(String(2))
    purpose: Mapped[str] = mapped_column(String(60))
    version: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(8), default="en")
    title: Mapped[str] = mapped_column(String(160))
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="PUBLISHED")  # DRAFT|PUBLISHED|RETIRED
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Consent(IdMixin, TimestampMixin, Base):
    __tablename__ = "consent"
    __table_args__ = (S,)

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    need_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    purpose: Mapped[str] = mapped_column(String(60))
    data_categories: Mapped[list[str]] = mapped_column(ARRAY(String))
    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    template_version: Mapped[str] = mapped_column(String(20))
    text_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="GRANTED")  # GRANTED|WITHDRAWN|EXPIRED
    channel: Mapped[str] = mapped_column(String(16), default="web")
    contact_channel: Mapped[str] = mapped_column(String(16), default="phone")
    contact_window: Mapped[str] = mapped_column(String(40), default="ANY")
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdraw_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CrbCheck(IdMixin, TimestampMixin, Base):
    """One Just-In-Time credit bureau pull (gnuGRID CRB), bound to the customer and the lender they selected.
    Holds the consent handshake and outcome only; the report lands as provenance-tagged facts, never as a raw payload."""

    __tablename__ = "crb_check"
    __table_args__ = (S,)

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    match_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(20))  # mock | gnugrid
    session_id: Mapped[str] = mapped_column(String(120))
    challenge_id: Mapped[str] = mapped_column(String(120))
    # PENDING|VERIFIED|MISMATCH|NOT_FOUND|EXPIRED|SUPERSEDED (identity details changed after the pull)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # the normalized report THIS lender may see
