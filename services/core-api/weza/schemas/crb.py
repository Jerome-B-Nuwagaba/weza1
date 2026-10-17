"""gnuGRID CRB contracts shared by the provider clients and the JIT consent service.

These are what WEZA sends to and reads from a credit bureau client. The API never takes the customer, NIN, phone or
institution from a request body: the service fills them from the authenticated session, the vault and the customer's
own lender selection."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CRBConsentRequest(BaseModel):
    customer_id: UUID
    national_id: str = Field(..., description="NIN or FCN number")
    phone_number: str = Field(..., description="E.164 phone number")
    selected_institution_id: UUID = Field(..., description="Target lender ID triggering JIT consent")


class CRBConsentOTPChallenge(BaseModel):
    session_id: str
    challenge_id: str
    masked_phone: str
    expires_in_seconds: int = 300


class CRBConsentOTPVerify(BaseModel):
    customer_id: UUID
    session_id: str
    challenge_id: str
    otp_code: str
    selected_institution_id: UUID


class CRBSummaryReport(BaseModel):
    crb_reference_id: str
    verification_status: Literal["VERIFIED", "NOT_FOUND", "MISMATCH"]
    credit_score_band: Literal["POOR", "FAIR", "GOOD", "EXCELLENT"] | None
    numeric_score: int | None
    active_loans_count: int
    has_active_defaults: bool
    total_outstanding_balance_ugx: float
