"""Identity verification attempts (CRB KYC enquiries). Holds outcomes and evidence — never names, dates of birth,
photos or raw bureau responses (data minimisation; see docs/CRB_VERIFICATION.md)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from weza.platform.db import Base, IdMixin, TimestampMixin


class VerificationCheck(IdMixin, TimestampMixin, Base):
    __tablename__ = "verification_check"
    __table_args__ = ({"schema": "identity"},)

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    need_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(24), default="CRB_KYC")
    provider: Mapped[str] = mapped_column(String(24), default="gnugrid")
    identification_type: Mapped[str] = mapped_column(String(48))
    identifier_index: Mapped[str] = mapped_column(String(64), index=True)  # blind index, never the identifier
    # Same customer + identifier + claimed name + claimed date of birth → same key: never enquire twice for it.
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True)
    # REQUESTED (sent, no answer yet) | COMPLETED | FAILED
    status: Mapped[str] = mapped_column(String(16), default="REQUESTED")
    # VERIFIED | DISCREPANCY | NO_RECORD | AMBIGUOUS | INCONCLUSIVE | PENDING | INSUFFICIENT_INFO | INVALID_IDENTIFIER
    # | UNAVAILABLE | UNCERTAIN | CONFIG_ERROR
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    field_results: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"name": MATCH|MISMATCH|NOT_CHECKED, "date_of_birth": ...}
    error_category: Mapped[str | None] = mapped_column(String(24), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bureau_enquiry_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bureau_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bureau_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    matches: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"formal": n, "informal": n}
    # consent evidence for the enquiry (client_consented = "Yes")
    consent_version: Mapped[str] = mapped_column(String(20))
    consent_text_hash: Mapped[str] = mapped_column(String(64))
    consent_channel: Mapped[str] = mapped_column(String(16))
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
