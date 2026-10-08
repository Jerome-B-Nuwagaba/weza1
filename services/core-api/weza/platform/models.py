"""Platform tables: outbox/deliveries, idempotency, graph runtime, flags and kill switches."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin, utcnow

S = {"schema": "platform"}


class OutboxEvent(IdMixin, Base):
    """Transactional outbox (TSD §55). Written in the same transaction as the business change."""

    __tablename__ = "outbox_event"
    __table_args__ = (Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id"), S)

    event_type: Mapped[str] = mapped_column(String(80), index=True)
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    topic: Mapped[str] = mapped_column(String(40), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(40))
    aggregate_id: Mapped[str] = mapped_column(String(64))
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class EventDelivery(IdMixin, Base):
    """One row per (event, consumer). Doubles as the consumer inbox: the unique constraint gives
    exactly-once *effect* with at-least-once delivery (TSD §56)."""

    __tablename__ = "event_delivery"
    __table_args__ = (UniqueConstraint("event_id", "consumer"), Index("ix_delivery_due", "status", "next_attempt_at"), S)

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.outbox_event.id"))
    consumer: Mapped[str] = mapped_column(String(80))
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING | DONE | DEAD
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_key"
    __table_args__ = (S,)

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    scope: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB, default=dict)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GraphInstance(IdMixin, TimestampMixin, Base):
    """Persisted workflow graph state (Skill §48). Never stored in chat history or LLM memory."""

    __tablename__ = "graph_instance"
    __table_args__ = (Index("ix_graph_timer", "status", "next_action_at"), S)

    graph_type: Mapped[str] = mapped_column(String(60), index=True)
    graph_version: Mapped[int] = mapped_column(Integer, default=1)
    current_node: Mapped[str] = mapped_column(String(60))
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")
    waiting_for: Mapped[str | None] = mapped_column(String(40), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    need_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class GraphTransition(IdMixin, Base):
    __tablename__ = "graph_transition"
    __table_args__ = (S,)

    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.graph_instance.id"),
                                                   index=True)
    from_node: Mapped[str] = mapped_column(String(60))
    to_node: Mapped[str] = mapped_column(String(60))
    trigger: Mapped[str] = mapped_column(String(60))
    autonomy_level: Mapped[int] = mapped_column(Integer, default=2)
    actor: Mapped[str] = mapped_column(String(80), default="system")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeatureFlag(Base):
    __tablename__ = "feature_flag"
    __table_args__ = (S,)

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KillSwitch(Base):
    """Audited network controls (TSD §75). value examples: {'on': true} or {'mode': 'DEGRADED'}."""

    __tablename__ = "kill_switch"
    __table_args__ = (S,)

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(80), default="system")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RateCounter(Base):
    """Fixed-window rate counters in Postgres so limits hold across processes (TSD §63).
    A Redis adapter can replace this without changing callers."""

    __tablename__ = "rate_counter"
    __table_args__ = (S,)

    bucket: Mapped[str] = mapped_column(String(200), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
