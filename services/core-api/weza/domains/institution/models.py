"""Institution (tenant), contacts, teams, routing rules, service targets, notification preferences."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin

S = {"schema": "institution"}


class Institution(IdMixin, TimestampMixin, Base):
    __tablename__ = "institution"
    __table_args__ = (S,)

    legal_name: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(120))
    institution_type: Mapped[str] = mapped_column(String(40))
    country_code: Mapped[str] = mapped_column(String(2), default="UG")
    licence_no: Mapped[str] = mapped_column(String(80), default="")
    regulator: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(24), default="SUBMITTED")
    terms_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)  # description, website, regions served, colour
    onboarding: Mapped[dict] = mapped_column(JSONB, default=dict)  # checklist cache


class Contact(IdMixin, Base):
    __tablename__ = "contact"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # REPRESENTATIVE | BUSINESS | COMPLIANCE
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(40), default="")
    title: Mapped[str] = mapped_column(String(120), default="")


class Team(IdMixin, TimestampMixin, Base):
    __tablename__ = "team"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(120))


class RoutingRule(IdMixin, TimestampMixin, Base):
    """Ordered assignment rule. conditions: {product_ids?, customer_types?, sectors?, regions?, min_amount?, max_amount?}"""

    __tablename__ = "routing_rule"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    name: Mapped[str] = mapped_column(String(120))
    conditions: Mapped[dict] = mapped_column(JSONB, default=dict)
    target_team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ServiceTarget(TimestampMixin, Base):
    __tablename__ = "service_target"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ack_within_minutes: Mapped[int] = mapped_column(Integer, default=120)
    first_contact_within_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    escalate_after_minutes: Mapped[int] = mapped_column(Integer, default=2880)


class NotificationPref(IdMixin, TimestampMixin, Base):
    __tablename__ = "notification_pref"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(60))
    channels: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: ["in_app"])
    min_priority: Mapped[str] = mapped_column(String(10), default="NORMAL")
    digest: Mapped[bool] = mapped_column(Boolean, default=False)
