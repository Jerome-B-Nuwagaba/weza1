"""Matching & market clearing (TSD §18–24): matches, clearing runs, simulations, waiting room."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin, utcnow

S = {"schema": "matching"}


class Match(IdMixin, TimestampMixin, Base):
    __tablename__ = "match"
    __table_args__ = (Index("ix_match_need_state", "need_id", "state"), S)

    need_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    product_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    appetite_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    appetite_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="CANDIDATE")
    eligibility: Mapped[list] = mapped_column(JSONB, default=list)  # per-rule PASS/FAIL/UNKNOWN results
    components: Mapped[dict] = mapped_column(JSONB, default=dict)
    score: Mapped[float] = mapped_column(Float, default=0)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explanation: Mapped[dict] = mapped_column(JSONB, default=dict)
    readiness: Mapped[str | None] = mapped_column(String(20), nullable=True)
    algorithm_version: Mapped[str] = mapped_column(String(20), default="match_v1")
    weights_version: Mapped[int] = mapped_column(Integer, default=1)
    ruleset_hash: Mapped[str] = mapped_column(String(64), default="")
    profile_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    clearing_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    invalidated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    presented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sponsored: Mapped[bool] = mapped_column(Boolean, default=False)  # never mixed into score (BR-008)


class ShadowMatch(IdMixin, Base):
    """Shadow-mode algorithm output (Skill §56). Never shown to customers."""

    __tablename__ = "shadow_match"
    __table_args__ = (S,)

    clearing_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    need_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    product_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    algorithm_version: Mapped[str] = mapped_column(String(20))
    score: Mapped[float] = mapped_column(Float)
    eligible: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClearingRun(IdMixin, Base):
    __tablename__ = "clearing_run"
    __table_args__ = (S,)

    trigger_event: Mapped[str] = mapped_column(String(80))
    trigger_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    needs_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    matches_created: Mapped[int] = mapped_column(Integer, default=0)
    invalidated: Mapped[int] = mapped_column(Integer, default=0)
    newly_matched_needs: Mapped[int] = mapped_column(Integer, default=0)
    algorithm_version: Mapped[str] = mapped_column(String(20), default="match_v1")
    shadow_algorithm_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SimulationRun(IdMixin, Base):
    __tablename__ = "simulation_run"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    appetite_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="APPETITE")  # APPETITE | SANDBOX | PRODUCT_GAP
    criteria: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WaitingEntry(TimestampMixin, Base):
    __tablename__ = "waiting_entry"
    __table_args__ = (S,)

    need_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default="OPTED_IN")  # OPTED_IN|MATCH_FOUND|RECONFIRM_DUE|EXPIRED|LEFT
    opted_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reconfirm_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    renewals: Mapped[int] = mapped_column(Integer, default=0)
    last_cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notify_channel: Mapped[str] = mapped_column(String(16), default="sms")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
