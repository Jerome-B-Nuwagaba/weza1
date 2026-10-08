"""Commercial engine (TSD §43–46): attribution, contracts, commercial events (append-only), disputes."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin, utcnow

S = {"schema": "commercial"}


class Partner(IdMixin, TimestampMixin, Base):
    __tablename__ = "partner"
    __table_args__ = (S,)

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(30), default="ASSOCIATION")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Campaign(IdMixin, TimestampMixin, Base):
    __tablename__ = "campaign"
    __table_args__ = (S,)

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    partner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Attribution(IdMixin, Base):
    """Immutable acquisition lineage (TSD §45)."""

    __tablename__ = "attribution"
    __table_args__ = (S,)

    source: Mapped[str] = mapped_column(String(40), default="direct")
    campaign_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    partner_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    referral_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="web")
    landing: Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contract(IdMixin, TimestampMixin, Base):
    """InstitutionContract (TSD §44). qualified_definition: {min_verification, min_match_score, require_consent,
    require_routing, exclude_synthetic}"""

    __tablename__ = "contract"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    plan: Mapped[str] = mapped_column(String(30), default="GROWTH")
    billing_cycle: Mapped[str] = mapped_column(String(12), default="MONTHLY")
    subscription_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    included_opportunities: Mapped[int] = mapped_column(Integer, default=0)
    opportunity_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    qualified_definition: Mapped[dict] = mapped_column(JSONB, default=dict)
    duplicate_window_days: Mapped[int] = mapped_column(Integer, default=30)
    dispute_window_days: Mapped[int] = mapped_column(Integer, default=14)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class CommercialEvent(IdMixin, Base):
    """Append-only. Corrections are REVERSAL/CREDIT events, never updates of amount (Skill §49)."""

    __tablename__ = "commercial_event"
    __table_args__ = (S,)

    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))  # QUALIFIED_OPPORTUNITY | REVERSAL | CREDIT | SUBSCRIPTION
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="UGX")
    status: Mapped[str] = mapped_column(String(20))  # BILLABLE | INCLUDED_IN_PLAN | NOT_BILLABLE | DISPUTED | REVERSED
    billing_period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    reverses_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    evaluation: Mapped[dict] = mapped_column(JSONB, default=dict)
    attribution: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dispute(IdMixin, TimestampMixin, Base):
    __tablename__ = "dispute"
    __table_args__ = (S,)

    commercial_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    state: Mapped[str] = mapped_column(String(24), default="OPEN")
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    history: Mapped[list] = mapped_column(JSONB, default=list)
