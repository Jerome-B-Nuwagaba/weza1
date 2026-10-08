"""Product Studio (FSD §19, TSD §16): products with immutable, effective-dated versions."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin

S = {"schema": "product"}


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "product"
    __table_args__ = (S,)

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(160))
    family: Mapped[str] = mapped_column(String(40))  # SME_WORKING_CAPITAL, ASSET_FINANCE, SALARY_LOAN, AGRI, ...
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class ProductVersion(IdMixin, TimestampMixin, Base):
    """terms: {min_amount, max_amount, min_tenor_months, max_tenor_months, pricing_display, collateral_required,
    digital_journey, typical_response_hours, description}
    rules: [{field, op, value, label}]  — deterministic eligibility (TSD §18)
    requirements: [{doc_type, label, required}]"""

    __tablename__ = "product_version"
    __table_args__ = (UniqueConstraint("product_id", "version"), S)

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT|PENDING_APPROVAL|APPROVED|SUPERSEDED|REJECTED
    name: Mapped[str] = mapped_column(String(160))
    family: Mapped[str] = mapped_column(String(40))
    terms: Mapped[dict] = mapped_column(JSONB, default=dict)
    rules: Mapped[list] = mapped_column(JSONB, default=list)
    requirements: Mapped[list] = mapped_column(JSONB, default=list)
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # AI extraction provenance
    ruleset_hash: Mapped[str] = mapped_column(String(64), default="")
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
