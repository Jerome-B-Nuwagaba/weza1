"""Trust plane: append-only audit (TSD §53), decision ledger (TSD §52), policy decision log (TSD §28)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, utcnow

S = {"schema": "trust"}


class AuditEvent(IdMixin, Base):
    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_object", "object_type", "object_id"), S)

    actor_type: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_display: Mapped[str] = mapped_column(String(120), default="")
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[str] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    versions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Decision(IdMixin, Base):
    __tablename__ = "decision"
    __table_args__ = (Index("ix_decision_subject", "subject_type", "subject_id"), S)

    decision_type: Mapped[str] = mapped_column(String(40), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    ruleset_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    algorithm_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    output: Mapped[dict] = mapped_column(JSONB, default=dict)
    explanation: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PolicyDecisionLog(IdMixin, Base):
    __tablename__ = "policy_decision_log"
    __table_args__ = (S,)

    actor: Mapped[str] = mapped_column(String(80))
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60))
    resource: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(60), default="")
    result: Mapped[str] = mapped_column(String(40))
    fields_permitted: Mapped[list] = mapped_column(JSONB, default=list)
    policy_version: Mapped[str] = mapped_column(String(20), default="policies_v1")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
