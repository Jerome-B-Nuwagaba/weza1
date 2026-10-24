"""Just-In-Time gnuGRID CRB check (GnuGrid Enquiries API v1.08).

The bureau is engaged only after a customer has chosen a specific lender (a SELECTED match, or consent granted to that
lender) AND said "Yes" to the bureau check. Intent capture, profiling and matching never call it, so every paid
enquiry belongs to a high-intent applicant on their way to becoming a Qualified Opportunity.

Flow: recorded consent (backs client_consented = "Yes") → one CreditEnquiry → deterministic identity decision →
for a confirmed identity, the CreditReport (json) reduced to a summary → facts, identity record, lender disclosure.

Cost protection (every SUCCESSFUL enquiry is charged; the API has no idempotency key):
- one bureau check per customer and lender at a time (advisory lock), and a result is reused for CRB_FRESH_DAYS;
- the check row and then the enquiry id are COMMITTED (own transaction) before the next bureau call, so a failure
  after a paid enquiry resumes with that enquiry instead of paying again;
- a timeout after sending, or a crash mid-request, becomes UNRESOLVED for operations — never resent automatically.

Credit data never blocks a request — lending decisions stay with the institution. Only an identity failure
(NOT_FOUND / MISMATCH) stops sharing; AMBIGUOUS, PENDING and bureau outages never do (they go to human review)."""

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.consent.models import Consent, CrbCheck
from weza.domains.customer import service as customer_svc
from weza.domains.customer.models import Customer
from weza.domains.identity import service as identity
from weza.domains.identity.models import OtpChallenge
from weza.domains.matching.models import Match
from weza.domains.need.models import FinancialNeed
from weza.domains.trust.service import audit
from weza.domains.verification import service as verification
from weza.domains.verification.adapters import VerificationResult
from weza.domains.verification.models import IdentityCheck
from weza.integrations.gnugrid import (
    CRBConfigError,
    CRBError,
    CRBUnavailable,
    CRBUncertain,
    get_crb_client,
    normalise_name,
)
from weza.platform import crypto
from weza.platform.context import Actor
from weza.platform.controls import rate_limit
from weza.platform.db import SessionLocal, get_engine, utcnow
from weza.platform.errors import NotFound, ValidationFailed
from weza.schemas.crb import CrbEnquiry, CrbProfile, CRBSummaryReport

SOURCE, STATE = "GNGRID_CRB", "VERIFIED_THIRD_PARTY"
CRB_FRESH_DAYS = 30  # a result for a lender is reused within this window instead of paying again
STALE_REQUEST = timedelta(minutes=10)  # a REQUESTED row older than this crashed mid-call: it may have been charged
MAX_NEW_ENQUIRIES_PER_DAY = 3  # per customer, across lenders
FAILED = ("MISMATCH", "NOT_FOUND")  # identity failures: the only outcomes that stop sharing
FINAL = ("VERIFIED", "MISMATCH", "NOT_FOUND", "AMBIGUOUS")
OPEN = ("REQUESTED", "ENQUIRED", "UNRESOLVED")
CRB_FACTS = {  # fact key -> report field
    "crb.reference": "crb_reference_id", "crb.score_band": "credit_score_band", "crb.numeric_score": "numeric_score",
    "crb.active_loans": "active_loans_count", "crb.has_active_defaults": "has_active_defaults",
    "crb.outstanding_balance": "total_outstanding_balance_ugx",
}
REPORT_LABEL = ("Credit bureau summary from gnuGRID CRB, shared with the customer's consent. WEZA does not make credit "
                "decisions — your institution performs its own KYC and underwriting.")

# ---------------------------------------------------------------- consent (DRAFT — needs legal approval)
CONSENT_VERSION = "2026.10-draft"
CONSENT_TEXT = ("To help {institution} review your request, WEZA can check your record at the credit reference bureau "
                "(GnuGrid CRB) using your National ID number and name. {institution} will see a summary of your "
                "credit history. Your credit history never stops your request, but if the bureau can't match your "
                "National ID and name, we won't share your request until they are corrected. Do you agree?")


def consent_text(institution: str) -> str:
    return CONSENT_TEXT.format(institution=institution)


def consent_hash(institution: str) -> str:
    return crypto.sha256_hex(consent_text(institution))


# ---------------------------------------------------------------- identity decision (pure, deterministic)


def name_matches(claimed: str | None, p: CrbProfile) -> bool:
    """The bureau surname and at least one bureau forename appear in the claimed full name (case, punctuation,
    accents and order ignored)."""
    words = set(normalise_name(claimed))
    surname = normalise_name(p.surname)
    forenames = [w for f in p.forenames for w in normalise_name(f)]
    return bool(surname) and all(w in words for w in surname) and any(w in words for w in forenames)


def _same_person(a: CrbProfile, b: CrbProfile) -> bool:
    return (normalise_name(a.surname) == normalise_name(b.surname)
            and normalise_name(" ".join(a.forenames[:1])) == normalise_name(" ".join(b.forenames[:1]))
            and (not a.date_of_birth or not b.date_of_birth or a.date_of_birth == b.date_of_birth))


def interpret(enquiry: CrbEnquiry, claimed_name: str | None) -> tuple[str, CrbProfile | None]:
    """Identity outcome of one enquiry. VERIFIED only with exactly one consistent profile whose name matches."""
    if enquiry.bureau_status in ("PENDING", "INCOMPLETE"):
        return "PENDING", None
    if any(n > 1 for n in enquiry.matches.values()):
        return "AMBIGUOUS", None  # the spec: matches "must always be 1 else it is a mismatch" — a human decides
    profiles = [p for p in enquiry.profiles if p.individual_id]
    if not profiles:
        return "NOT_FOUND", None
    if any(not _same_person(profiles[0], p) for p in profiles[1:]):
        return "AMBIGUOUS", None  # formal and informal records disagree
    if not claimed_name:
        return "AMBIGUOUS", None
    chosen = next((p for p in profiles if p.sector == "formal"), profiles[0])
    return ("VERIFIED", chosen) if name_matches(claimed_name, chosen) else ("MISMATCH", None)


# ---------------------------------------------------------------- the check


def _selection(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID) -> uuid.UUID | None:
    """The match through which this customer chose this lender, or None if they haven't chosen it."""
    m = db.execute(select(Match.id).join(FinancialNeed, FinancialNeed.id == Match.need_id)
                   .outerjoin(Consent, Consent.match_id == Match.id).where(
        FinancialNeed.customer_id == customer_id, Match.institution_id == institution_id,
        or_(Consent.id.is_(None), Consent.status == "GRANTED"),
        Match.state == "SELECTED")).first()
    if m:
        return m[0]
    c = db.execute(select(Consent.match_id).where(Consent.customer_id == customer_id, Consent.status == "GRANTED",
                                                  Consent.institution_id == institution_id)).first()
    return c[0] if c else None


def _require_selection(db: Session, actor: Actor, institution_id: uuid.UUID) -> uuid.UUID:
    if actor.kind != "CUSTOMER" or actor.id is None:
        raise NotFound("Customer not found.")
    match_id = _selection(db, actor.id, institution_id)
    if match_id is None:
        raise ValidationFailed("Choose this institution from your options first.", code="LENDER_NOT_SELECTED")
    return match_id


def issue_consent_otp(db: Session, actor: Actor, institution_id: uuid.UUID, *, channel: str) -> dict:
    """WEZA's lender-bound consent OTP. v1.08 has no bureau OTP endpoint; no provider is called here."""
    match_id = _require_selection(db, actor, institution_id)
    customer = db.get(Customer, actor.id)
    vault = identity.vault_read(db, customer.vault_token)
    if not vault.get("nin"):
        raise ValidationFailed("Save your National ID before verification.", code="NIN_REQUIRED")
    settings, now = get_settings(), utcnow()
    rate_limit(db, f"crb:otp:{actor.id}", 5, 900)
    for old in db.execute(select(CrbCheck).where(CrbCheck.customer_id == actor.id,
            CrbCheck.institution_id == institution_id, CrbCheck.status == "OTP_PENDING")).scalars():
        old.status = "SUPERSEDED"
    code = f"{secrets.randbelow(10_000_000_000):010d}"
    salt = crypto.new_salt()
    check = CrbCheck(customer_id=actor.id, institution_id=institution_id, match_id=match_id,
                     provider="gnugrid" if settings.is_production and not settings.gngrid_use_mock else "mock",
                     status="OTP_PENDING", consent_version=CONSENT_VERSION,
                     consent_text_hash=consent_hash(_inst_name(db, institution_id)), consent_channel=channel[:16],
                     expires_at=now + timedelta(seconds=settings.otp_ttl_seconds))
    db.add(check)
    db.flush()
    challenge = OtpChallenge(phone_index=crypto.blind_index("phone", vault["phone"]),
                              code_hash=crypto.hash_otp(code, salt), salt=salt, expires_at=check.expires_at,
                              last_sent_at=now, channel="crb", journey_id=check.id)
    db.add(challenge)
    db.flush()
    check.challenge_id = str(challenge.id)
    from weza.domains.notification.service import send_customer_message
    delivered = send_customer_message(db, vault["phone"],
        f"Your WEZA consent code for {_inst_name(db, institution_id)} is {code}. "
        "Enter it in your application to authorise the credit bureau check. It expires in 5 minutes.",
        channel="sms", kind="otp")
    if not delivered:
        check.status, challenge.status = "FAILED", "FAILED_DELIVERY"
        raise ValidationFailed("We couldn't send the code. Please try again.", code="OTP_DELIVERY_FAILED")
    return {"challenge_id": challenge.id, "selected_institution_id": institution_id,
            "expires_at": check.expires_at, "masked": identity.mask_phone(vault["phone"]), "digits": 10,
            "dev_code": code if settings.otp_delivery == "display" and not settings.is_production else None}


def _verify_consent_otp(own: Session, actor: Actor, institution_id: uuid.UUID,
                        challenge_id: uuid.UUID | None, otp: str | None) -> CrbCheck:
    if not challenge_id or not otp:
        raise ValidationFailed("Verify the lender consent code before the bureau check.", code="CRB_OTP_REQUIRED")
    check = own.execute(select(CrbCheck).where(CrbCheck.customer_id == actor.id,
        CrbCheck.institution_id == institution_id, CrbCheck.challenge_id == str(challenge_id))
        .with_for_update()).scalar_one_or_none()
    if check is None:
        raise NotFound("Consent challenge not found.")
    if check.status != "OTP_PENDING":
        raise ValidationFailed("Request a new consent code.", code="OTP_EXPIRED")
    result = identity.verify_otp(own, challenge_id, otp)
    settings = get_settings()
    # A deliberate adverse-credit fixture, available solely against the offline bureau after selection.
    if (not result.ok and otp == "000000" and not settings.is_production and check.provider == "mock"
            and result.code == "OTP_INCORRECT"):
        result.ok, result.challenge.status = True, "VERIFIED"
        check.provider_ref = "mock_defaults"
    if not result.ok:
        own.commit()  # wrong attempts/expiry survive the API request rollback
        raise ValidationFailed(result.message, code=result.code)
    check.status, check.consented_at = "OTP_VERIFIED", utcnow()
    own.commit()  # durable OTP authorisation precedes any chargeable request
    return check


def _latest(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID, statuses) -> CrbCheck | None:
    return db.execute(select(CrbCheck).where(CrbCheck.customer_id == customer_id,
                                             CrbCheck.institution_id == institution_id, CrbCheck.status.in_(statuses))
                      .order_by(CrbCheck.created_at.desc()).limit(1)).scalar_one_or_none()


def reusable(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID) -> CrbCheck | None:
    """A check for this lender that must not be paid for again: a fresh final result, or one still open."""
    c = _latest(db, customer_id, institution_id, (*FINAL, *OPEN))
    if c is None:
        return None
    if c.status in OPEN:
        return c
    return c if (c.verified_at or c.created_at) > utcnow() - timedelta(days=CRB_FRESH_DAYS) else None


def _review(own: Session, kind: str, title: str, check: CrbCheck, severity: str = "MEDIUM", **detail) -> None:
    from weza.domains.integrity.service import add_review
    add_review(own, kind, title, "crb_check", check.id, severity=severity,
               detail={"institution_id": str(check.institution_id), "status": check.status, **detail},
               dedupe_key=f"{kind}:{check.id}")


def _ops_alert(own: Session, exc: CRBError, check: CrbCheck) -> None:
    from weza.domains.integrity.service import add_review
    what = {"AUTH": "credentials were rejected", "BILLING": f"subscription/float problem ({exc.billing_state})",
            "CONFIG": "is not configured", "INVALID": "rejected the request", "PROTOCOL": "returned an unreadable answer"}
    add_review(own, "CRB_UNAVAILABLE", f"Credit bureau {what.get(exc.category, 'is failing')}: {exc.message}"[:200],
               "integration", "gnugrid", severity="HIGH", detail={"category": exc.category, "http": exc.http_status,
                                                                    "check_id": str(check.id)},
               dedupe_key=f"CRB_UNAVAILABLE:{exc.category}")


def _fetch_report(own: Session, check: CrbCheck, client) -> CRBSummaryReport | None:
    try:
        report = client.credit_report(check.enquiry_id, check.individual_id, reference=check.enquiry_reference
                                      or check.enquiry_id)
    except CRBConfigError as exc:
        check.error_category = exc.category
        _ops_alert(own, exc, check)
        return None
    except CRBError as exc:
        check.error_category = exc.category  # stays ENQUIRED: resumed next time with the same (already paid) enquiry
        return None
    check.status, check.verified_at, check.summary, check.error_category = "VERIFIED", utcnow(), \
        report.model_dump(), None
    return report


def run_check(db: Session, actor: Actor, institution_id: uuid.UUID, *, channel: str,
              challenge_id: uuid.UUID | None = None, otp: str | None = None) -> dict:
    """The customer chose this lender and said "Yes" to the bureau check. Returns the outcome; never raises for a
    bureau problem (the request continues without a report)."""
    _require_selection(db, actor, institution_id)
    customer = db.get(Customer, actor.id)
    vault = identity.vault_read(db, customer.vault_token)
    if not vault.get("nin"):
        return {"status": "SKIPPED", "outcome": None, "report": None, "reason": "NIN_REQUIRED"}
    s = get_settings()
    fresh_outcome = report = None
    # One check per customer and lender at a time. The advisory lock lives on its own connection, held for the whole
    # call (a Session may switch pooled connections after each commit, which would strand a session-level lock).
    lock, lock_conn = f"crb:{actor.id}:{institution_id}", get_engine().connect().execution_options(
        isolation_level="AUTOCOMMIT")
    try:
        lock_conn.execute(text("SET lock_timeout = '30s'"))
        lock_conn.execute(text("SELECT pg_advisory_lock(hashtextextended(:k, 0))"), {"k": lock})
    except OperationalError:
        lock_conn.close()
        return {"status": "IN_PROGRESS", "outcome": None, "report": None, "reason": "CHECK_IN_PROGRESS"}
    own = SessionLocal()  # own transactions: what the bureau charged for is kept even if the caller rolls back
    try:
        client = get_crb_client() if not s.is_production or s.gngrid_use_mock or not s.crb_missing else None
        check = reusable(own, actor.id, institution_id)
        if check is not None and check.status == "REQUESTED" and check.created_at < utcnow() - STALE_REQUEST:
            check.status, check.error_category = "UNRESOLVED", "UNCERTAIN"  # crashed after sending: may be charged
            _review(own, "CRB_CHECK_UNRESOLVED", "Credit bureau check interrupted after sending; it may have been "
                    "charged. Confirm with GnuGrid before running it again.", check)
            own.commit()
        if check is not None and check.status == "ENQUIRED" and client is not None:
            report = _fetch_report(own, check, client)  # resume: same enquiry, no new charge
            fresh_outcome = "REPORT" if report else None  # identity was recorded when the enquiry ran
            own.commit()
        elif check is None:
            check = _verify_consent_otp(own, actor, institution_id, challenge_id, otp)
            if client is None:
                return {"status": "FAILED", "outcome": None, "report": None, "reason": "NOT_CONFIGURED"}
            today = own.execute(select(CrbCheck.id).where(
                CrbCheck.customer_id == actor.id, CrbCheck.created_at > utcnow() - timedelta(days=1),
                CrbCheck.enquiry_id.is_not(None))).all()
            if len(today) >= MAX_NEW_ENQUIRIES_PER_DAY:
                return {"status": "FAILED", "outcome": None, "report": None, "reason": "DAILY_LIMIT"}
            check.provider, check.status, check.attempts = client.name, "REQUESTED", 1
            if client.name == "mock":
                client.simulate_defaults = check.provider_ref == "mock_defaults"
            own.commit()  # consent evidence and the intent to enquire exist before anything is sent
            try:
                enquiry = client.credit_enquiry(vault["nin"], claimed_name=vault.get("full_name"))
            except CRBUncertain as exc:
                check.status, check.error_category = "UNRESOLVED", exc.category
                _review(own, "CRB_CHECK_UNRESOLVED", "Credit bureau enquiry may have been processed (no answer). "
                        "Confirm with GnuGrid before running it again.", check)
            except CRBConfigError as exc:
                check.status, check.error_category = "FAILED", exc.category
                if exc.category != "INVALID_IDENTIFIER":
                    _ops_alert(own, exc, check)
            except CRBUnavailable as exc:
                check.status, check.error_category = "FAILED", exc.category
            else:
                check.enquiry_id, check.enquiry_reference = enquiry.enquiry_id, enquiry.reference
                check.bureau_status, check.cost = enquiry.bureau_status, enquiry.cost
                if enquiry.bureau_status == "FAILED":
                    check.status, check.error_category = "FAILED", "BUREAU_FAILED"
                else:
                    outcome, profile = interpret(enquiry, vault.get("full_name"))
                    if outcome == "PENDING":
                        check.status = "UNRESOLVED"
                        _review(own, "CRB_CHECK_UNRESOLVED", "Credit bureau enquiry is still pending at GnuGrid.",
                                check, bureau_status=enquiry.bureau_status)
                    elif outcome == "VERIFIED":
                        check.status, check.individual_id = "ENQUIRED", profile.individual_id
                        own.commit()  # the paid enquiry is on record before the report is requested
                        report = _fetch_report(own, check, client)
                        fresh_outcome = "VERIFIED"
                    else:
                        check.status, check.verified_at, fresh_outcome = outcome, utcnow(), outcome
                        if outcome in ("MISMATCH", "AMBIGUOUS"):
                            _review(own, "IDENTITY_UNVERIFIED", f"Credit bureau identity check: {outcome}. Not an "
                                    "indication of fraud on its own; review before relying on the identity.", check,
                                    matches=enquiry.matches)
            own.commit()
        check_id, status, summary = check.id, check.status, check.summary
        provider, reference = check.provider, check.enquiry_reference or check.enquiry_id
        verified_at = check.verified_at
    finally:
        own.close()
        try:
            lock_conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": lock})
        finally:
            lock_conn.close()

    shown = report or (CRBSummaryReport(**summary) if summary else None)
    if fresh_outcome or status in FINAL:
        _apply(db, actor, check_id, institution_id, fresh_outcome or status, provider, reference, shown)
    return {"check_id": str(check_id), "status": status, "outcome": status if status in FINAL else None,
            "report": shown.model_dump() if shown else None, "reused": fresh_outcome is None and status in FINAL,
            "verified_at": verified_at.isoformat() if verified_at else None}


def _inst_name(db: Session, institution_id: uuid.UUID) -> str:
    from weza.domains.institution.models import Institution
    inst = db.get(Institution, institution_id)
    return inst.display_name if inst else "the institution"


def _apply(db: Session, actor: Actor, check_id: uuid.UUID, institution_id: uuid.UUID, outcome: str, provider: str,
           reference: str | None, report: CRBSummaryReport | None) -> None:
    """Record a new outcome in the caller's transaction: audit, identity, and (for a report) provenance-tagged facts.
    outcome REPORT = a resumed report for an identity already recorded: only the facts are added."""
    from weza.domains.trust.models import AuditEvent
    # Serialize projection repair with other responses for this customer. Paid results survive a caller rollback.
    db.execute(select(Customer.id).where(Customer.id == actor.id).with_for_update()).first()
    if outcome == "REPORT" and not db.execute(select(AuditEvent.id).where(
            AuditEvent.object_id == str(check_id), AuditEvent.institution_id == institution_id,
            AuditEvent.actor_id == str(actor.id), AuditEvent.action == "GNGRID_CRB_CHECK_COMPLETED")).first():
        outcome = "VERIFIED"
    action = "GNGRID_CRB_REPORT_RECEIVED" if outcome == "REPORT" else "GNGRID_CRB_CHECK_COMPLETED"
    if db.execute(select(AuditEvent.id).where(AuditEvent.object_id == str(check_id),
            AuditEvent.institution_id == institution_id, AuditEvent.actor_id == str(actor.id),
            AuditEvent.action == action)).first():
        return
    audit(db, actor, action,
          "crb_check", check_id, institution_id=institution_id,
          after={"status": outcome, "provider": provider, "reference": reference, "consent_version": CONSENT_VERSION})
    if outcome in ("VERIFIED", *FAILED):
        ic = IdentityCheck(customer_id=actor.id, check_type="NIN", status="PENDING", attempts=1,
                           provider="gnugrid_crb" if provider == "gnugrid" else "crb_mock")
        db.add(ic)
        db.flush()
        verification.record_result(db, ic, VerificationResult(outcome, name_match=outcome != "MISMATCH",
                                                              provider_ref=reference))
    if report is not None:
        for key, field in CRB_FACTS.items():
            value = getattr(report, field)
            if value is not None:
                fact, _ = customer_svc.upsert_fact(db, actor.id, key, value, source=SOURCE, channel="crb", confirmed=True,
                                                  source_ref=f"crb_check:{check_id}", verification_state=STATE)
                # Equal values still acquire the latest bureau provenance (upsert otherwise refreshes only age).
                if fact:
                    fact.source, fact.verification_state = SOURCE, STATE
                    fact.source_ref, fact.captured_at = f"crb_check:{check_id}", utcnow()
        from weza.domains.matching import engine
        for need in db.execute(select(FinancialNeed).where(FinancialNeed.customer_id == actor.id,
                FinancialNeed.status.notin_(("CLOSED", "EXPIRED")))).scalars():
            engine.match_need(db, need, trigger="GNGRID_CRB")


# ---------------------------------------------------------------- reads used elsewhere


def latest_check(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID) -> CrbCheck | None:
    """The latest completed pull for this lender that still applies (not superseded by changed identity details)."""
    return _latest(db, customer_id, institution_id, (*FINAL, "ENQUIRED"))


def supersede_checks(db: Session, customer_id: uuid.UUID) -> None:
    """The customer's NIN or name changed: earlier pulls (and any failure they recorded) no longer apply."""
    for c in db.execute(select(CrbCheck).where(CrbCheck.customer_id == customer_id,
                                               CrbCheck.status.in_((*FINAL, "ENQUIRED", "FAILED", "OTP_PENDING",
                                                                    "OTP_VERIFIED")))).scalars():
        c.status = "SUPERSEDED"


def blocks_sharing(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID) -> bool:
    """Only an identity failure blocks; credit history, ambiguity and bureau outages never do."""
    c = latest_check(db, customer_id, institution_id)
    return bool(c and c.status in FAILED)


def report_for_institution(db: Session, customer_id: uuid.UUID, institution_id: uuid.UUID) -> dict | None:
    """The credit summary the customer consented to share with this lender, or None."""
    c = latest_check(db, customer_id, institution_id)
    if c is None or c.status != "VERIFIED" or not c.summary:
        return None
    return {**c.summary, "pulled_at": c.verified_at.isoformat(), "label": REPORT_LABEL}
