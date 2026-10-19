"""gnuGRID CRB contracts shared by the bureau clients and the Just-In-Time service (GnuGrid Enquiries API v1.08).

The service never takes the customer, NIN or lender from a request body: they come from the authenticated session, the
identity vault and the customer's own lender selection. Only these normalised fields are ever stored or shown — never
the bureau's raw payload (which carries photos, contact details and addresses)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CRBConsentRequest(BaseModel):
    selected_institution_id: uuid.UUID
    consent: bool


class CRBConsentOTPChallenge(BaseModel):
    challenge_id: uuid.UUID
    selected_institution_id: uuid.UUID
    expires_at: datetime
    masked: str
    digits: int = 10
    dev_code: str | None = None


class CRBConsentOTPVerify(CRBConsentRequest):
    challenge_id: uuid.UUID | None = None
    otp: str | None = Field(None, min_length=6, max_length=10, pattern=r"^[0-9]+$")

# Identity outcome of one credit enquiry, decided by WEZA's deterministic rules (crb_service.interpret)
IdentityOutcome = Literal["VERIFIED", "MISMATCH", "NOT_FOUND", "AMBIGUOUS", "PENDING"]


class CrbProfile(BaseModel):
    """One matched person from the enquiry's formal or informal dataset (names only; nothing else is kept)."""
    sector: str
    individual_id: str | None
    surname: str
    forenames: list[str]
    date_of_birth: str | None = None


class CrbEnquiry(BaseModel):
    """Result of POST /v1/credit-enquiries/request/new. Every SUCCESSFUL enquiry is charged."""
    enquiry_id: str
    reference: str | None = None
    bureau_status: str | None = None  # PENDING | INCOMPLETE | SUCCESSFUL | FAILED
    cost: float | None = None
    matches: dict[str, int] = {}  # sector -> number of matches
    profiles: list[CrbProfile] = []


class CRBSummaryReport(BaseModel):
    """What WEZA keeps from POST /v1/credit-enquiries/individual/credit-report (format=json), and shares with the
    chosen lender under consent."""
    crb_reference_id: str
    verification_status: Literal["VERIFIED", "NOT_FOUND", "MISMATCH"] = "VERIFIED"
    credit_score_band: Literal["POOR", "FAIR", "GOOD", "EXCELLENT"] | None = None
    score_grade: str | None = None  # bureau's own band code, e.g. "AAA"
    numeric_score: int | None = None
    probability_of_default: str | None = None  # e.g. "6.25%"
    active_loans_count: int = 0
    adverse_accounts: int = 0
    worst_days_in_arrears: int | None = None
    has_active_defaults: bool = False
    total_outstanding_balance_ugx: float = 0.0
