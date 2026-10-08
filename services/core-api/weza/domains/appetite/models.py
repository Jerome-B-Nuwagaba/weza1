"""Appetite Studio & capital mandates (FSD §20, TSD §17, §24). Lifecycle and capacity are separate fields
(blueprint conflict C2)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin

S = {"schema": "appetite"}


class Appetite(IdMixin, TimestampMixin, Base):
    __tablename__ = "appetite"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(160))
    lifecycle_status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    capacity_state: Mapped[str] = mapped_column(String(10), default="ACTIVE")  # ACTIVE|LIMITED|FULL|PAUSED
    capacity_override: Mapped[str | None] = mapped_column(String(10), nullable=True)  # manual PAUSED/LIMITED
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    fulfilled_count: Mapped[int] = mapped_column(Integer, default=0)
    fulfilled_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)


class AppetiteVersion(IdMixin, TimestampMixin, Base):
    """criteria: [{field, op, value, label, weight, must}] — `must` criteria exclude; others shape appetite fit.
    capacity_limits: {daily_count, weekly_count, monthly_count, monthly_value}"""

    __tablename__ = "appetite_version"
    __table_args__ = (UniqueConstraint("appetite_id", "version"), S)

    appetite_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT|SIMULATED|APPROVED|SUPERSEDED|REJECTED
    name: Mapped[str] = mapped_column(String(160))
    product_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    criteria: Mapped[list] = mapped_column(JSONB, default=list)
    min_match_score: Mapped[int] = mapped_column(Integer, default=60)
    target_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    capacity_limits: Mapped[dict] = mapped_column(JSONB, default=dict)
    campaign_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    campaign_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ruleset_hash: Mapped[str] = mapped_column(String(64), default="")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class CapacityUsage(Base):
    __tablename__ = "capacity_usage"
    __table_args__ = (S,)

    appetite_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    window: Mapped[str] = mapped_column(String(8), primary_key=True)  # DAY|WEEK|MONTH
    window_start: Mapped[date] = mapped_column(Date, primary_key=True)
    count_used: Mapped[int] = mapped_column(Integer, default=0)
    value_used: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
