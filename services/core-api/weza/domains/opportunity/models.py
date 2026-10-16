"""Qualified Opportunity (TSD Â§30â€“33), assignment, reported outcomes, previews/interest, insights."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin, utcnow

S = {"schema": "opportunity"}


class Opportunity(IdMixin, TimestampMixin, Base):
    __tablename__ = "opportunity"
    __table_args__ = (Index("ix_opp_inst_state", "institution_id", "state"), S)

    reference: Mapped[str] = mapped_column(String(16), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    need_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    appetite_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    consent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    state: Mapped[str] = mapped_column(String(28), default="QUALIFIED")
    freshness: Mapped[str] = mapped_column(String(20), default="FRESH")
    routing_strategy: Mapped[str] = mapped_column(String(24), default="CUSTOMER_SELECTED")
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)  # frozen versioned inputs (FSD-OPP-002)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    match_score: Mapped[float] = mapped_column(Float)
    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[str] = mapped_column(String(8), default="NORMAL")  # NORMAL|HIGH|URGENT
    sector: Mapped[str | None] = mapped_column(String(40), nullable=True)
    district: Mapped[str | None] = mapped_column(String(60), nullable=True)
    customer_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    purpose_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attribution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    qualified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    routed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    integrity_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Assignment(TimestampMixin, Base):
    __tablename__ = "assignment"
    __table_args__ = (S,)

    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_by: Mapped[str] = mapped_column(String(16), default="RULE")  # RULE | USER | UNASSIGNED
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ack_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_contact_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_action_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    breach_state: Mapped[str] = mapped_column(String(16), default="ON_TRACK")  # ON_TRACK|APPROACHING|BREACHED|ESCALATED|MET
    breach_count: Mapped[int] = mapped_column(Integer, default=0)


class Outcome(IdMixin, Base):
    """Institution-reported marketplace outcome (BR-005: always labelled 'reported')."""

    __tablename__ = "outcome"
    __table_args__ = (S,)

    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    state: Mapped[str] = mapped_column(String(28))
    reason_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    disbursed_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    disbursed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    reported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Activity(IdMixin, Base):
    __tablename__ = "activity"
    __table_args__ = (S,)

    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InfoRequest(IdMixin, TimestampMixin, Base):
    """Institution → customer request for a document or an answer on a routed opportunity. WEZA relays it;
    the customer chooses whether to respond, and nothing outside the consented categories is ever requested."""

    __tablename__ = "info_request"
    __table_args__ = (Index("ix_info_request_opp_status", "opportunity_id", "status"), S)

    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # DOCUMENT | QUESTION
    doc_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="OPEN")  # OPEN | FULFILLED | CANCELLED
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Preview(IdMixin, TimestampMixin, Base):
    """Level-2 non-identifiable preview (TSD Â§25). payload is produced by an allow-list serializer."""

    __tablename__ = "preview"
    __table_args__ = (S,)

    need_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    interest_state: Mapped[str] = mapped_column(String(24), default="PENDING")
    interest_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Insight(IdMixin, TimestampMixin, Base):
    """Outcome-learning / no-lead / product-gap insight for human review (FSD Â§35). Never auto-applied."""

    __tablename__ = "insight"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # APPETITE_OUTCOME_MISMATCH | LOW_FILL | PRODUCT_GAP
    appetite_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    title: Mapped[str] = mapped_column(String(240))
    narrative: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN|DISMISSED|ACTIONED
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
