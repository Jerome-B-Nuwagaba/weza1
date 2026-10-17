"""Identity verification against the Credit Reference Bureau (advisory; see docs/CRB_VERIFICATION.md).

Flow: consent (recorded on the check) → input validation → idempotency (never enquire twice for the same customer,
identifier, claimed name and date of birth) → GnuGrid KYC enquiry → deterministic interpretation → outcome stored →
customer facts / verification level updated. The AI never sees bureau data and never decides an outcome.

Matching rule (approved 2026-10-16): VERIFIED only when the bureau returns exactly one consistent individual profile,
the claimed date of birth equals the bureau's, and the bureau surname plus at least one bureau forename appear in the
claimed full name (case, punctuation, accents and word order ignored). Anything else is never "verified".
"""

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.verification import gnugrid
from weza.domains.verification.models import VerificationCheck
from weza.platform import crypto
from weza.platform.db import SessionLocal, utcnow
from weza.platform.events import emit

log = logging.getLogger("weza.crb")

# ---------------------------------------------------------------- consent (DRAFT — needs legal approval)
CONSENT_VERSION = "2026.1-draft"
CONSENT_TEXT = (
    "To check your identity, WEZA will send your National ID number to GnuGrid CRB, a licensed credit reference "
    "bureau in Uganda, and compare the name and date of birth you gave us with their record. WEZA keeps only the "
    "result (match or no match), not the bureau's record. This check does not approve or reject a loan. "
    "Do you agree?")
CONSENT_TEXT_HASH = crypto.sha256_hex(CONSENT_TEXT)

TERMINAL = {"VERIFIED", "DISCREPANCY", "NO_RECORD", "AMBIGUOUS", "INCONCLUSIVE", "PENDING", "UNCERTAIN",
            "INVALID_IDENTIFIER"}
RETRYABLE = {"UNAVAILABLE", "CONFIG_ERROR"}
MAX_ATTEMPTS_PER_KEY = 3
RETRY_GAP = timedelta(hours=1)
STALE_REQUEST = timedelta(minutes=10)


@dataclass
class CheckOutcome:
    outcome: str
    field_results: dict
    check_id: uuid.UUID | None = None
    reused: bool = False


# ---------------------------------------------------------------- deterministic interpretation


def _tokens(s: str | None) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).upper()
    return [t for t in re.split(r"[^A-Z]+", s) if t]


def compare_name(claimed: str | None, p: gnugrid.CrbIndividual) -> str:
    claimed_t = set(_tokens(claimed))
    surname = _tokens(p.surname)
    forenames = {t for f in p.forenames for t in _tokens(f)}
    if not claimed_t or not surname or not forenames:
        return "NOT_CHECKED"
    return "MATCH" if set(surname) <= claimed_t and forenames & claimed_t else "MISMATCH"


def compare_dob(claimed_iso: str | None, p: gnugrid.CrbIndividual) -> str:
    if not claimed_iso or not p.date_of_birth or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.date_of_birth):
        return "NOT_CHECKED"
    return "MATCH" if claimed_iso == p.date_of_birth else "MISMATCH"


def _same_person(a: gnugrid.CrbIndividual, b: gnugrid.CrbIndividual) -> bool:
    return (set(_tokens(a.surname)) == set(_tokens(b.surname)) and a.date_of_birth == b.date_of_birth
            and {t for f in a.forenames for t in _tokens(f)} == {t for f in b.forenames for t in _tokens(f)})


def interpret(res: gnugrid.EnquiryResult, claimed_name: str | None, claimed_dob: str | None) -> tuple[str, dict]:
    """Bureau answer → (outcome, field_results). Pure function: no I/O."""
    not_checked = {"name": "NOT_CHECKED", "date_of_birth": "NOT_CHECKED"}
    if not res.ok:
        return {gnugrid.UNAVAILABLE: "UNAVAILABLE", gnugrid.UNCERTAIN: "UNCERTAIN",
                gnugrid.INVALID_IDENTIFIER: "INVALID_IDENTIFIER"}.get(res.category, "CONFIG_ERROR"), not_checked
    if res.bureau_status in ("PENDING", "INCOMPLETE"):
        return "PENDING", not_checked  # the API offers no way to fetch the final result (see doc, ambiguities)
    if res.bureau_status != "SUCCESSFUL":
        return "UNAVAILABLE", not_checked  # FAILED or an unknown status: the enquiry did not complete
    if any(n > 1 for n in res.matches.values()):
        return "AMBIGUOUS", not_checked  # spec: matches must be exactly 1, otherwise it is a mismatch
    profiles = [p for p in res.individuals if res.matches.get(p.sector) == 1]
    if not profiles:
        return "NO_RECORD", not_checked
    first = profiles[0]
    if any(not _same_person(first, p) for p in profiles[1:]):
        return "AMBIGUOUS", not_checked  # formal and informal records describe different people
    fields = {"name": compare_name(claimed_name, first), "date_of_birth": compare_dob(claimed_dob, first)}
    if "MISMATCH" in fields.values():
        return "DISCREPANCY", fields
    if "NOT_CHECKED" in fields.values():
        return "INCONCLUSIVE", fields  # e.g. the bureau record has no date of birth: cannot be "verified"
    return "VERIFIED", fields


# ---------------------------------------------------------------- orchestration


def _claims(db: Session, customer_id: uuid.UUID) -> dict:
    from weza.domains.customer.models import Customer
    from weza.domains.identity.service import vault_read
    cust = db.get(Customer, customer_id)
    v = vault_read(db, cust.vault_token) if cust else {}
    return {"nin": v.get("nin"), "full_name": v.get("full_name"), "date_of_birth": v.get("date_of_birth")}


def _key(customer_id: uuid.UUID, claims: dict) -> str:
    return crypto.sha256_hex("|".join([str(customer_id), crypto.blind_index("nin", claims["nin"]),
                                       " ".join(sorted(_tokens(claims["full_name"]))), claims["date_of_birth"]]))


def latest(db: Session, customer_id: uuid.UUID) -> VerificationCheck | None:
    return db.execute(select(VerificationCheck).where(VerificationCheck.customer_id == customer_id)
                      .order_by(VerificationCheck.created_at.desc()).limit(1)).scalar_one_or_none()


def status_for(db: Session, customer_id: uuid.UUID) -> dict:
    """What institutions and staff see: outcome of the latest check for the customer's current identity details."""
    claims = _claims(db, customer_id)
    if not (claims["nin"] and claims["full_name"] and claims["date_of_birth"]):
        last = None
    else:
        key = _key(customer_id, claims)
        last = db.execute(select(VerificationCheck).where(VerificationCheck.idempotency_key == key)
                          .order_by(VerificationCheck.created_at.desc()).limit(1)).scalar_one_or_none()
    if last is None:
        return {"identity_check": "NOT_CHECKED", "source": None, "checked_at": None}
    return {"identity_check": last.outcome or "IN_PROGRESS", "source": "GnuGrid CRB KYC enquiry",
            "checked_at": (last.completed_at or last.created_at).isoformat(), "fields": last.field_results}


def missing_for_check(db: Session, customer_id: uuid.UUID) -> list[str]:
    claims = _claims(db, customer_id)
    return [k for k in ("nin", "full_name", "date_of_birth") if not claims.get(k)]


def needs_check(db: Session, customer_id: uuid.UUID) -> bool:
    """True when the bureau is configured, a NIN was given, and no final result exists for the current details."""
    if not get_settings().crb_ready:
        return False
    claims = _claims(db, customer_id)
    if not claims["nin"]:
        return False  # the customer chose not to give a NIN: nothing to check (advisory)
    if not (claims["full_name"] and claims["date_of_birth"]):
        return True  # still needs the date of birth (asked by the journey)
    key = _key(customer_id, claims)
    rows = db.execute(select(VerificationCheck).where(VerificationCheck.idempotency_key == key)).scalars().all()
    if any(r.outcome in TERMINAL for r in rows):
        return False
    return len(rows) < MAX_ATTEMPTS_PER_KEY


def run_check(db: Session, customer_id: uuid.UUID, *, need_id: uuid.UUID | None, channel: str,
              consented_at) -> CheckOutcome:
    """Run (or reuse) the identity check for the customer's current details. The caller has just recorded the
    customer's explicit consent for this enquiry (`consented_at`)."""
    s = get_settings()
    claims = _claims(db, customer_id)
    if not s.crb_ready:
        return CheckOutcome("NOT_CONFIGURED", {})
    if not (claims["nin"] and claims["full_name"] and claims["date_of_birth"]):
        return CheckOutcome("INSUFFICIENT_INFO", {})
    key = _key(customer_id, claims)

    # Claim the attempt in its own committed transaction (survives a crash after the paid call) under a lock, so
    # retries of the same webhook or a double tap can never submit a second enquiry for the same details.
    own = SessionLocal()
    try:
        own.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"crb:{key}"})
        rows = own.execute(select(VerificationCheck).where(VerificationCheck.idempotency_key == key)
                           .order_by(VerificationCheck.created_at.desc())).scalars().all()
        now = utcnow()
        for r in rows:
            if r.status == "REQUESTED" and now - r.created_at > STALE_REQUEST:
                r.status, r.outcome, r.completed_at = "FAILED", "UNCERTAIN", now  # crashed mid-call: never resubmit
        done = next((r for r in rows if r.outcome in TERMINAL or r.status == "REQUESTED"), None)
        recent_retry = next((r for r in rows if r.outcome in RETRYABLE and now - r.created_at < RETRY_GAP), None)
        if done is not None or recent_retry is not None or len(rows) >= MAX_ATTEMPTS_PER_KEY:
            r = done or recent_retry or rows[0]
            own.commit()
            return CheckOutcome(r.outcome or "PENDING", r.field_results or {}, r.id, reused=True)
        row = VerificationCheck(customer_id=customer_id, need_id=need_id, identification_type="ii_country_id",
                                identifier_index=crypto.blind_index("nin", claims["nin"]), idempotency_key=key,
                                status="REQUESTED", consent_version=CONSENT_VERSION,
                                consent_text_hash=CONSENT_TEXT_HASH, consent_channel=channel[:16],
                                consented_at=consented_at)
        own.add(row)
        own.commit()
        check_id = row.id
    finally:
        own.close()

    res = gnugrid.kyc_enquiry_individual(claims["nin"], gnugrid.IDENTIFICATION_TYPES["NIN"])
    outcome, fields = interpret(res, claims["full_name"], claims["date_of_birth"])

    own = SessionLocal()
    try:
        row = own.get(VerificationCheck, check_id)
        row.status = "COMPLETED" if res.ok else "FAILED"
        row.outcome, row.field_results, row.completed_at = outcome, fields, utcnow()
        row.error_category = None if res.ok else res.category
        row.http_status, row.bureau_enquiry_id, row.bureau_reference = res.http_status, res.enquiry_id, res.reference
        row.bureau_status, row.cost, row.matches = res.bureau_status, res.cost, res.matches
        own.commit()
    finally:
        own.close()

    _apply(db, customer_id, outcome)
    emit(db, "IdentityCheckCompleted", topic="customer", aggregate_type="customer", aggregate_id=customer_id,
         data={"outcome": outcome, "check_id": str(check_id)})
    if outcome in ("CONFIG_ERROR", "UNCERTAIN", "PENDING"):
        from weza.domains.integrity.service import add_review
        if outcome == "CONFIG_ERROR":
            add_review(db, "CRB_UNAVAILABLE", f"CRB identity checks are failing ({res.category}, HTTP "
                       f"{res.http_status}). Check CRB_* settings, credentials and the GnuGrid subscription"
                       + (f" ({res.billing_state})." if res.billing_state else "."), "integration", "crb",
                       severity="HIGH", detail={"category": res.category, "http": res.http_status,
                                                "billing": res.billing_state}, dedupe_key="CRB_UNAVAILABLE")
        else:
            add_review(db, "CRB_CHECK_UNRESOLVED", f"A CRB identity check ended {outcome}; it is not resubmitted "
                       "automatically (it may have been processed and charged).", "verification_check", check_id,
                       severity="MEDIUM", detail={"outcome": outcome, "bureau_status": res.bureau_status})
    log.info("crb_check_done", extra={"data": {"outcome": outcome, "category": res.category}})
    return CheckOutcome(outcome, fields, check_id)


def _apply(db: Session, customer_id: uuid.UUID, outcome: str) -> None:
    """Project the outcome onto the customer: verification level and the `identity.crb_verified` fact."""
    from weza.domains.customer import service as customer_svc
    from weza.domains.customer.models import Customer
    cust = db.get(Customer, customer_id)
    verified = outcome == "VERIFIED"
    if verified:
        cust.verification_level = "IDENTITY"
    elif cust.verification_level == "IDENTITY":
        cust.verification_level = "PHONE"
    fact, _ = customer_svc.upsert_fact(db, customer_id, "identity.crb_verified", verified, source="CRB",
                                       confirmed=True, source_ref=outcome)
    if fact is not None and verified:
        fact.verification_state = "VERIFIED"
        for f in customer_svc.current_facts(db, customer_id).values():
            if f.key in ("identity.nin_captured", "identity.full_name_captured",
                         "identity.date_of_birth_captured"):
                f.verification_state = "VERIFIED"


def attempts_today(db: Session, customer_id: uuid.UUID) -> int:
    return db.execute(select(func.count()).select_from(VerificationCheck).where(
        VerificationCheck.customer_id == customer_id,
        VerificationCheck.created_at >= utcnow() - timedelta(days=1))).scalar_one()
