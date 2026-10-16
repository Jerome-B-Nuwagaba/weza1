"""Identity verification against an external registry (e.g. gnuGRID). One row per check attempt; holds the outcome
only — never the NIN (which stays in the vault) or the provider's raw response."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin

S = {"schema": "customer"}


class IdentityCheck(IdMixin, TimestampMixin, Base):
    __tablename__ = "identity_check"
    __table_args__ = (S,)

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    check_type: Mapped[str] = mapped_column(String(16), default="NIN")
    provider: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING|VERIFIED|MISMATCH|NOT_FOUND|ERROR
    name_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dob_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
