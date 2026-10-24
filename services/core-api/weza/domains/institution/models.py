"""Institution (tenant), contacts, teams, routing rules, service targets, notification preferences."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin

S = {"schema": "institution"}

#: The institution lifecycle the product specification names, projected onto the internal state machine.
#: The internal statuses stay authoritative (they drive the transition rules in institution/service.py);
#: this is the four-state view every client reads.
CANONICAL_STATUS = {
    "DRAFT": "draft", "SUBMITTED": "pending_review", "UNDER_VERIFICATION": "pending_review",
    "APPROVED": "pending_review", "CONFIGURING": "pending_review", "READY": "pending_review",
    "REJECTED": "draft", "CLOSED": "draft",
    "ACTIVE": "active", "PAUSED": "paused", "SUSPENDED": "paused",
}


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

    @property
    def canonical_status(self) -> str:
        """draft | pending_review | active | paused — the four states the product specification names."""
        return CANONICAL_STATUS.get(self.status, "draft")

    @property
    def is_primary_contact_known(self) -> bool:
        return bool(self.profile.get("primary_contact"))


class Contact(IdMixin, Base):
    __tablename__ = "contact"
    __table_args__ = (
        # At most one primary contact per institution, enforced by the database.
        Index("uq_contact_primary_per_institution", "institution_id", unique=True,
              postgresql_where=text("is_primary")),
        S,
    )

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # REPRESENTATIVE | BUSINESS | COMPLIANCE
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(40), default="")
    title: Mapped[str] = mapped_column(String(120), default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)  # the contact WEZA reaches first


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
