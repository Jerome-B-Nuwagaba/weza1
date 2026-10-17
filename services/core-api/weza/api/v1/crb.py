"""Customer Just-In-Time credit bureau consent (/me/crb). The customer is always the signed-in customer; NIN and phone
come from the identity vault; the lender must be one the customer has already selected."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from weza.api.deps import DB, customer_actor
from weza.domains.consent import crb_service
from weza.platform.context import Actor

router = APIRouter(prefix="/me/crb", tags=["crb"])


class ConsentRequestIn(BaseModel):
    selected_institution_id: uuid.UUID


class ConsentVerifyIn(BaseModel):
    session_id: str = Field(..., max_length=120)
    challenge_id: str = Field(..., max_length=120)
    otp_code: str = Field(..., min_length=4, max_length=12)


@router.post("/consent/request")
def request_consent(body: ConsentRequestIn, actor: Actor = Depends(customer_actor), db: Session = DB):
    """The bureau sends the customer a consent code for the lender they selected."""
    return crb_service.request_crb_consent(db, actor, body.selected_institution_id)


@router.post("/consent/verify")
def verify_consent(body: ConsentVerifyIn, actor: Actor = Depends(customer_actor), db: Session = DB):
    """The customer enters the code; WEZA records consent, identity and the credit summary."""
    return crb_service.verify_and_enrich_customer_crb(db, actor, body.session_id, body.challenge_id, body.otp_code)
