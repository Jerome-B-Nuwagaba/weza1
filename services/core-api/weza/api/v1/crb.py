"""Customer Just-In-Time credit bureau check (/me/crb). The customer is always the signed-in customer; the NIN comes
from the identity vault; the lender must be one the customer has already selected; consent is explicit."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from weza.api.deps import DB, customer_actor
from weza.domains.consent import crb_service
from weza.platform.context import Actor
from weza.platform.errors import ValidationFailed

router = APIRouter(prefix="/me/crb", tags=["crb"])


class CrbCheckIn(BaseModel):
    selected_institution_id: uuid.UUID
    consent: bool  # the customer said "Yes" to crb_service.CONSENT_TEXT for this institution


@router.get("/consent-text")
def consent_text(institution_id: uuid.UUID, actor: Actor = Depends(customer_actor), db: Session = DB):
    """The exact text the customer agrees to (draft, versioned)."""
    return {"version": crb_service.CONSENT_VERSION,
            "text": crb_service.consent_text(crb_service._inst_name(db, institution_id))}


@router.post("/check")
def run_check(body: CrbCheckIn, actor: Actor = Depends(customer_actor), db: Session = DB):
    """Run (or reuse) the bureau check for the lender the customer selected."""
    if not body.consent:
        raise ValidationFailed("Consent is required for the credit bureau check.", code="CRB_CONSENT_REQUIRED")
    return crb_service.run_check(db, actor, body.selected_institution_id, channel="app")
