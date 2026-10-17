"""Just-In-Time gnuGRID CRB consent gate.

The bureau is engaged only when a customer has selected a specific lender (a SELECTED match, or consent already
granted to that lender) and then completes gnuGRID's consent code. Intent capture, profiling and matching never call
it, so every paid pull belongs to a high-intent applicant on their way to becoming a Qualified Opportunity.

The customer, NIN, phone and lender are never taken from the request: they come from the authenticated session, the
identity vault and the customer's own selection. One pull returns both identity status and the credit summary, so
identity is recorded here too (verification.record_result) and no separate registry call is needed.

Credit data is recorded and shared with the chosen lender under consent; it never blocks a request. Only an identity
failure (NOT_FOUND / MISMATCH) stops sharing — lending decisions stay with the institution."""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.domains.consent.models import Consent, CrbCheck
from weza.domains.customer import service as customer_svc
from weza.domains.customer.models import Customer
from weza.domains.identity import service as identity
from weza.domains.matching.models import Match
from weza.domains.need.models import FinancialNeed
from weza.domains.trust.service import audit
from weza.domains.verification import service as verification
from weza.domains.verification.adapters import VerificationResult
from weza.domains.verification.models import IdentityCheck
from weza.integrations.gnugrid import CRBOTPInvalid, CRBUnavailable, get_crb_client, mask
from weza.platform.context import Actor
from weza.platform.controls import rate_limit
from weza.platform.db import utcnow
from weza.platform.errors import NotFound, ValidationFailed, WezaError
from weza.schemas.crb import CRBConsentOTPVerify, CRBConsentRequest

SOURCE, STATE = "GNGRID_CRB", "VERIFIED_THIRD_PARTY"
CRB_FRESH_DAYS = 30  # a pull for a lender is reused within this window instead of paying again
FAILED = ("MISMATCH", "NOT_FOUND")
CRB_FACTS = {  # fact key -> report field
    "crb.reference": "crb_reference_id", "crb.score_band": "credit_score_band", "crb.numeric_score": "numeric_score",
    "crb.active_loans": "active_loans_count", "crb.has_active_defaults": "has_active_defaults",
    "crb.outstanding_balance": "total_outstanding_balance_ugx",
}
REPORT_LABEL = ("Credit bureau summary from gnuGRID CRB, shared with the customer's consent. WEZA does not make credit "
                "decisions — your institution performs its own KYC and underwriting.")


class CRBServiceUnavailable(WezaError):
    status = 503
    code = "CRB_UNAVAILABLE"
    retryable = True


def _selection(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID) -> uuid.UUID | None:
    """The match through which this customer chose this lender, or None if they haven't chosen it."""
    m = db.execute(select(Match.id).join(FinancialNeed, FinancialNeed.id == Match.need_id).where(
        FinancialNeed.customer_id == customer_id, Match.institution_id == institution_id,
        Match.state == "SELECTED")).first()
    if m:
        return m[0]
    c = db.execute(select(Consent.match_id).where(Consent.customer_id == customer_id, Consent.status == "GRANTED",
                                                  Consent.institution_id == institution_id)).first()
    return c[0] if c else None


def request_crb_consent(db: Session, actor: Actor, institution_id: uuid.UUID) -> dict:
    """Step 1: the customer has chosen a lender; ask the bureau to send them a consent code."""
    match_id = _selection(db, actor.id, institution_id)
    if match_id is None:
        raise ValidationFailed("Choose this institution from your options first.", code="LENDER_NOT_SELECTED")
    customer = db.get(Customer, actor.id)
    vault = identity.vault_read(db, customer.vault_token)
    if not vault.get("nin"):
        raise ValidationFailed("Add your National ID number in your profile first.", code="NIN_REQUIRED")
    # Never pay twice: a current result for this lender is reused, and an open challenge is handed back
    done = latest_check(db, actor.id, institution_id)
    if done is not None and done.verified_at > utcnow() - timedelta(days=CRB_FRESH_DAYS):
        return {"check_id": str(done.id), "status": done.status, "reused": True}
    pending = db.execute(select(CrbCheck).where(CrbCheck.customer_id == actor.id,
                                                CrbCheck.institution_id == institution_id,
                                                CrbCheck.status == "PENDING", CrbCheck.expires_at > utcnow())
                         .order_by(CrbCheck.created_at.desc()).limit(1)).scalar_one_or_none()
    if pending is not None:
        return {"check_id": str(pending.id), "session_id": pending.session_id, "challenge_id": pending.challenge_id,
                "masked_phone": mask(vault.get("phone") or ""), "reused": True,
                "expires_in_seconds": int((pending.expires_at - utcnow()).total_seconds())}
    rate_limit(db, f"crb_request:{actor.id}", 5, 3600, "Too many credit check attempts. Try again in an hour.")
    try:
        client = get_crb_client()
        challenge = client.request_consent_otp(CRBConsentRequest(
            customer_id=actor.id, national_id=vault["nin"], phone_number=vault.get("phone") or "",
            selected_institution_id=institution_id))
    except CRBUnavailable as exc:
        raise CRBServiceUnavailable("The credit bureau isn't available right now. Please try again shortly.") from exc
    check = CrbCheck(customer_id=actor.id, institution_id=institution_id, match_id=match_id, provider=client.name,
                     session_id=challenge.session_id, challenge_id=challenge.challenge_id, status="PENDING",
                     expires_at=utcnow() + timedelta(seconds=challenge.expires_in_seconds))
    db.add(check)
    db.flush()
    audit(db, actor, "GNGRID_CRB_CONSENT_REQUESTED", "crb_check", check.id, institution_id=institution_id,
          after={"provider": client.name})
    return {"check_id": str(check.id), **challenge.model_dump()}


def verify_and_enrich_customer_crb(db: Session, actor: Actor, session_id: str, challenge_id: str,
                                   otp_code: str) -> dict:
    """Step 2: the customer enters the bureau's code. Records consent, identity and the credit summary as
    third-party-verified facts, then re-clears the customer's demand (readiness/quality) via IdentityVerified."""
    check = db.execute(select(CrbCheck).where(CrbCheck.customer_id == actor.id, CrbCheck.session_id == session_id,
                                              CrbCheck.challenge_id == challenge_id)).scalar_one_or_none()
    if check is None:
        raise NotFound("Not found.")
    if check.status != "PENDING":
        raise ValidationFailed("This credit check is already complete.", code="CRB_NOT_PENDING")
    if check.expires_at <= utcnow():
        check.status = "EXPIRED"
        return {"status": "EXPIRED", "message": "That code has expired. Please request a new one."}
    # Counted in its own transaction, so wrong codes still count when this request fails
    rate_limit(db, f"crb_otp:{check.id}", 5, 900, "Too many wrong codes. Please request a new one later.")
    check.attempts += 1
    try:
        report = get_crb_client().verify_otp_and_pull_summary(CRBConsentOTPVerify(
            customer_id=actor.id, session_id=session_id, challenge_id=challenge_id, otp_code=otp_code,
            selected_institution_id=check.institution_id))
    except CRBOTPInvalid as exc:
        raise ValidationFailed("That code isn't right. Please check it and try again.", code="CRB_OTP_INVALID") from exc
    except CRBUnavailable as exc:
        raise CRBServiceUnavailable("The credit bureau isn't available right now. Please try again shortly.") from exc

    now = utcnow()
    check.status, check.verified_at, check.provider_ref = report.verification_status, now, report.crb_reference_id
    if report.verification_status == "VERIFIED":
        check.summary = report.model_dump()  # disclosed only to this lender, whatever is pulled for others later
    audit(db, actor, "GNGRID_CRB_CONSENT_GRANTED", "crb_check", check.id, institution_id=check.institution_id,
          before={"status": "PENDING"}, after={"status": report.verification_status, "provider": check.provider,
                                               "reference": report.crb_reference_id})
    ic = IdentityCheck(customer_id=actor.id, check_type="NIN", status="PENDING", attempts=1,
                       provider="gnugrid_crb" if check.provider == "gnugrid" else "crb_mock")
    db.add(ic)
    db.flush()
    verification.record_result(db, ic, VerificationResult(report.verification_status,
                                                          provider_ref=report.crb_reference_id))
    saved = []
    if report.verification_status == "VERIFIED":
        for key, field in CRB_FACTS.items():
            value = getattr(report, field)
            if value is None:
                continue
            customer_svc.upsert_fact(db, actor.id, key, value, source=SOURCE, channel="crb", confirmed=True,
                                     source_ref=f"crb_check:{check.id}", verification_state=STATE)
            saved.append(key)
    return {"status": report.verification_status, "crb_reference_id": report.crb_reference_id,
            "report": report.model_dump() if report.verification_status == "VERIFIED" else None,
            "facts_saved": saved, "identity": verification.summary(db, actor.id)}


def latest_check(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID) -> CrbCheck | None:
    """The latest completed pull for this lender that still applies (not superseded by changed identity details)."""
    return db.execute(select(CrbCheck).where(CrbCheck.customer_id == customer_id,
                                             CrbCheck.institution_id == institution_id,
                                             CrbCheck.status.in_(["VERIFIED", *FAILED]))
                      .order_by(CrbCheck.created_at.desc()).limit(1)).scalar_one_or_none()


def supersede_checks(db: Session, customer_id: uuid.UUID) -> None:
    """The customer's NIN or name changed: earlier pulls (and any failure they recorded) no longer apply."""
    for c in db.execute(select(CrbCheck).where(CrbCheck.customer_id == customer_id,
                                               CrbCheck.status.in_(["PENDING", "VERIFIED", *FAILED]))).scalars():
        c.status = "SUPERSEDED"


def blocks_sharing(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID) -> bool:
    """Only an identity failure blocks; credit history never does."""
    c = latest_check(db, customer_id, institution_id)
    return bool(c and c.status in FAILED)


def report_for_institution(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID) -> dict | None:
    """The credit summary the customer consented to share with this lender, or None."""
    c = latest_check(db, customer_id, institution_id)
    if c is None or c.status != "VERIFIED" or not c.summary:
        return None
    return {**c.summary, "pulled_at": c.verified_at.isoformat(), "label": REPORT_LABEL}

