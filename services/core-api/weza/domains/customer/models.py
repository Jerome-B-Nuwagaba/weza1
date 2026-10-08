"""Customer domain: customer, provenance-tracked facts (TSD Â§11), immutable profile snapshots (TSD Â§14),
preferences and documents (TSD Â§42)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin, utcnow

S = {"schema": "customer"}


class Customer(IdMixin, TimestampMixin, Base):
    __tablename__ = "customer"
    __table_args__ = (S,)

    vault_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    customer_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # SME|SALARIED|AGRICULTURE
    country_code: Mapped[str] = mapped_column(String(2), default="UG")
    verification_level: Mapped[str] = mapped_column(String(16), default="PHONE")  # NONE|PHONE|IDENTITY
    integrity_state: Mapped[str] = mapped_column(String(16), default="NORMAL")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    attribution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    device_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Fact(IdMixin, Base):
    """A single consequential customer fact with provenance. Superseded rather than overwritten."""

    __tablename__ = "fact"
    __table_args__ = (Index("ix_fact_current", "customer_id", "key", "superseded_at"), S)

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customer.customer.id"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[dict] = mapped_column(JSONB)  # {"v": <value>}
    source: Mapped[str] = mapped_column(String(16))  # CUSTOMER | AI_EXTRACTED | DOCUMENT | OPS
    source_channel: Mapped[str] = mapped_column(String(16), default="web")
    source_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification_state: Mapped[str] = mapped_column(String(16), default="SELF_REPORTED")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProfileSnapshot(IdMixin, Base):
    __tablename__ = "profile_snapshot"
    __table_args__ = (S,)

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    facts: Mapped[dict] = mapped_column(JSONB)
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Preference(TimestampMixin, Base):
    __tablename__ = "preference"
    __table_args__ = (S,)

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    contact_channel: Mapped[str] = mapped_column(String(16), default="phone")
    contact_window: Mapped[str] = mapped_column(String(40), default="ANY")
    ranking: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    language: Mapped[str] = mapped_column(String(8), default="en")


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "document"
    __table_args__ = (S,)

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    need_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    doc_type: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    pipeline_state: Mapped[str] = mapped_column(String(16), default="UPLOADED")
    scan_result: Mapped[str | None] = mapped_column(String(80), nullable=True)
    classification: Mapped[str] = mapped_column(String(20), default="HIGHLY_SENSITIVE")
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class DocumentBlob(Base):
    """Encrypted file bytes (ObjectStore adapter: Postgres in V1, Azure Blob later â€” blueprint C6)."""

    __tablename__ = "document_blob"
    __table_args__ = (S,)

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=True)

