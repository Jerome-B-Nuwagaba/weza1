"""Smaller domain tables: notifications (TSD §34), channel messages, integrity (TSD §41),
admin configuration (TSD §71), AI call log (TSD §67)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin, utcnow


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notification"
    __table_args__ = ({"schema": "notification"},)

    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(60))
    recipient_type: Mapped[str] = mapped_column(String(16))  # USER | CUSTOMER | WEZA_OPS
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(16))  # in_app | email | sms | whatsapp
    priority: Mapped[str] = mapped_column(String(8), default="NORMAL")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(200), nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")  # QUEUED|SENT|DELIVERED|FAILED|DEAD|READ|ACKED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    ack_required: Mapped[bool] = mapped_column(Boolean, default=False)
    ack_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)


class ChannelMessage(IdMixin, Base):
    """Outbound SMS/WhatsApp to customers. In demo mode the simulator reads these instead of a real provider."""

    __tablename__ = "channel_message"
    __table_args__ = ({"schema": "notification"},)

    channel: Mapped[str] = mapped_column(String(16))
    to_index: Mapped[str] = mapped_column(String(64), index=True)  # phone blind index — never the raw number
    body: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    provider: Mapped[str] = mapped_column(String(20), default="simulator")
    status: Mapped[str] = mapped_column(String(16), default="SENT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    # Provider delivery tracking (WhatsApp Cloud API): wamid, last callback status (sent|delivered|read|failed)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stable logical-send key. Used by journey/channel retries to avoid creating duplicate sends after a committed attempt.
    idempotency_key: Mapped[str | None] = mapped_column(String(180), nullable=True, unique=True)


class WhatsappStatusReceipt(Base):
    """Delivery status that arrived before its outbound ChannelMessage became visible.

    Meta can deliver sent/delivered/read callbacks extremely quickly. Keeping the latest early receipt lets a worker
    reconcile it later instead of silently losing delivery truth.
    """

    __tablename__ = "whatsapp_status_receipt"
    __table_args__ = ({"schema": "notification"},)

    provider_message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WhatsappInbox(IdMixin, Base):
    """One row per inbound WhatsApp message id (Meta retries are deduplicated by the unique key).
    Content is stored encrypted until processed, then wiped. See notification/whatsapp_inbound.py."""

    __tablename__ = "whatsapp_inbox"
    __table_args__ = ({"schema": "notification"},)

    provider_message_id: Mapped[str] = mapped_column(String(128), unique=True)
    msg_type: Mapped[str] = mapped_column(String(24))
    phone_index: Mapped[str] = mapped_column(String(64), index=True)  # blind index — never the raw number
    payload_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PENDING|DONE|DROPPED|IGNORED|FAILED (FAILED = gave up after processing errors; escalated for review)
    status: Mapped[str] = mapped_column(String(12), default="PENDING", index=True)
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # processing errors so far
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegritySignal(IdMixin, Base):
    __tablename__ = "signal"
    __table_args__ = ({"schema": "integrity"},)

    kind: Mapped[str] = mapped_column(String(40))
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    weight: Mapped[int] = mapped_column(Integer)
    rule_version: Mapped[str] = mapped_column(String(20), default="integrity_v1")
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntegrityCase(IdMixin, TimestampMixin, Base):
    __tablename__ = "case"
    __table_args__ = ({"schema": "integrity"},)

    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[int] = mapped_column(Integer)
    risk_state: Mapped[str] = mapped_column(String(16))  # REVIEW | HIGH_RISK | BLOCKED
    state: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | DECIDED
    result: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ALLOW | BLOCK
    signals: Mapped[list] = mapped_column(JSONB, default=list)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConfigVersion(IdMixin, Base):
    """Versioned admin configuration: country config, question paths, match weights (TSD §71; blueprint 04 §4)."""

    __tablename__ = "config_version"
    __table_args__ = (UniqueConstraint("key", "version"), {"schema": "admin"})

    key: Mapped[str] = mapped_column(String(60), index=True)  # country:UG | question_paths:UG | match_weights
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewItem(IdMixin, TimestampMixin, Base):
    """Human Control Centre queue (Skill §59)."""

    __tablename__ = "review_item"
    __table_args__ = ({"schema": "admin"},)

    kind: Mapped[str] = mapped_column(String(40))  # LOW_CONFIDENCE_AI | FACT_CONFLICT | INTEGRITY | ROUTING_FAILURE | DEAD_LETTER | GRAPH_FAILED | DUPLICATE_HOLD
    title: Mapped[str] = mapped_column(String(240))
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    resolved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiCallLog(IdMixin, Base):
    __tablename__ = "ai_call_log"
    __table_args__ = ({"schema": "analytics"},)

    capability: Mapped[str] = mapped_column(String(40), index=True)
    prompt_version: Mapped[str] = mapped_column(String(20))
    schema_version: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(12))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    validation_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MarketSnapshot(IdMixin, Base):
    __tablename__ = "market_snapshot"
    __table_args__ = ({"schema": "analytics"},)

    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class LoopMetric(IdMixin, Base):
    """Per-loop/per-agent budget and outcome telemetry (Skill §61)."""

    __tablename__ = "loop_metric"
    __table_args__ = ({"schema": "analytics"},)

    loop: Mapped[str] = mapped_column(String(40), index=True)
    event: Mapped[str] = mapped_column(String(40))  # ENTER|COMPLETE|EXHAUSTED|ESCALATED|FALLBACK
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value: Mapped[float] = mapped_column(Float, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
