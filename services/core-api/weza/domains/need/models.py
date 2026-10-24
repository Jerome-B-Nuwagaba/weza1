"""Financial Need (TSD §15) and canonical conversation messages (TSD §6)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin, utcnow

S = {"schema": "need"}


class FinancialNeed(IdMixin, TimestampMixin, Base):
    __tablename__ = "financial_need"
    __table_args__ = (Index("ix_need_status", "status"), S)

    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    journey_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    need_type: Mapped[str] = mapped_column(String(16), default="CREDIT")
    product_family: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    customer_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(40), nullable=True)
    district: Mapped[str | None] = mapped_column(String(60), nullable=True)
    region: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tenor_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    # Whether this journey's phone number has been proven reachable, and how. The OTP proves the
    # number is reachable by this customer — nothing more (WEZA V1 boundary).
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_verification_method: Mapped[str | None] = mapped_column(String(24), nullable=True)  # OTP | WHATSAPP_CHANNEL
    readiness: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_factors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    intent_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    intent_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    waiting_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attribution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ConversationMessage(IdMixin, Base):
    """Canonical message contract. Content is stored redacted; the journey graph is the workflow state."""

    __tablename__ = "conversation_message"
    __table_args__ = (Index("ix_msg_session", "session_id", "received_at"), S)

    message_id: Mapped[str] = mapped_column(String(120), unique=True)  # channel message id (dedupe)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # journey graph instance id
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    channel: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(8))  # IN | OUT
    message_type: Mapped[str] = mapped_column(String(20), default="TEXT")
    content: Mapped[dict] = mapped_column(JSONB, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
