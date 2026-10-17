"""Identity verification service. A captured NIN is checked against the configured registry asynchronously (outbox
consumer), so a slow or unavailable provider never blocks the customer's conversation. Only a VERIFIED result marks
the customer as identity-verified; failures raise integrity signals; errors are retried and never count."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.customer.models import Customer, Fact
from weza.domains.identity import service as identity
from weza.domains.trust.service import audit
from weza.domains.verification.adapters import IDENTITY_PROVIDERS
from weza.domains.verification.models import IdentityCheck
from weza.platform.context import SYSTEM
from weza.platform.db import utcnow
from weza.platform.events import emit

FAILED = ("MISMATCH", "NOT_FOUND")
PROVIDER_LABELS = {"simulator": "WEZA test registry", "gnugrid": "gnuGRID", "gnugrid_crb": "gnuGRID",
                   "crb_mock": "WEZA test bureau"}


class ProviderUnavailable(Exception):
    """Raised by run_check on an ERROR result so the outbox retries with backoff."""


def latest(db: Session, customer_id: uuid.UUID) -> IdentityCheck | None:
    return db.execute(select(IdentityCheck).where(IdentityCheck.customer_id == customer_id)
                      .order_by(IdentityCheck.created_at.desc()).limit(1)).scalar_one_or_none()


def summary(db: Session, customer_id: uuid.UUID) -> dict:
    """Non-identifying verification status for institution and customer views (never the NIN or provider data)."""
    c = latest(db, customer_id)
    if c is None:
        return {"status": "NOT_CHECKED", "label": "National ID not checked"}
    label = {"VERIFIED": f"National ID verified via {PROVIDER_LABELS.get(c.provider, c.provider)}",
             "MISMATCH": "National ID details didn't match the registry",
             "NOT_FOUND": "National ID not found in the registry",
             "PENDING": "National ID check in progress", "ERROR": "National ID check in progress"}[c.status]
    return {"status": c.status if c.status != "ERROR" else "PENDING", "provider": PROVIDER_LABELS.get(c.provider, c.provider),
            "checked_at": c.checked_at.isoformat() if c.checked_at else None, "label": label}


def request_check(db: Session, customer: Customer) -> IdentityCheck:
    c = IdentityCheck(customer_id=customer.id, check_type="NIN", provider=get_settings().identity_provider,
                      status="PENDING")
    db.add(c)
    db.flush()
    return c


def run_check(db: Session, check: IdentityCheck) -> IdentityCheck:
    """Call the registry once. ERROR → ProviderUnavailable (the outbox retries); other outcomes are final."""
    customer = db.get(Customer, check.customer_id)
    vault = identity.vault_read(db, customer.vault_token)
    adapter = IDENTITY_PROVIDERS.get(check.provider)
    check.attempts += 1
    result = adapter(vault.get("nin") or "", vault.get("full_name")) if adapter else None
    if result is None or result.status == "ERROR":
        check.status, check.last_error = "ERROR", (result.error if result else "unknown provider")[:500]
        raise ProviderUnavailable(check.last_error)
    return record_result(db, check, result)


def record_result(db: Session, check: IdentityCheck, result) -> IdentityCheck:
    """Apply a final registry outcome (VERIFIED | MISMATCH | NOT_FOUND) to the check and the customer. Used by the
    capture-time check above and by the Just-In-Time CRB pull, which returns identity status in the same call."""
    customer = db.get(Customer, check.customer_id)
    check.status, check.checked_at = result.status, utcnow()
    check.name_match, check.dob_match, check.provider_ref = result.name_match, result.dob_match, result.provider_ref
    check.last_error = None
    audit(db, SYSTEM, f"identity.{result.status.lower()}", "customer", customer.id,
          after={"provider": check.provider, "check": str(check.id)})
    if result.status == "VERIFIED":
        customer.verification_level = "IDENTITY"
        fact = db.execute(select(Fact).where(Fact.customer_id == customer.id, Fact.key == "identity.nin_captured",
                                             Fact.superseded_at.is_(None))).scalar_one_or_none()
        if fact is not None:
            fact.verification_state, fact.source, fact.source_ref = "VERIFIED", "REGISTRY", f"identity_check:{check.id}"
            fact.confirmed_at = check.checked_at
        emit(db, "IdentityVerified", topic="customer", aggregate_type="customer", aggregate_id=customer.id,
             data={"check_id": str(check.id), "provider": check.provider})
    else:
        if customer.verification_level == "IDENTITY":
            customer.verification_level = "PHONE"
        emit(db, "IdentityVerificationFailed", topic="customer", aggregate_type="customer", aggregate_id=customer.id,
             data={"check_id": str(check.id), "status": result.status})
    return check


def latest_statuses(db: Session, customer_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Latest check status per customer in one query (list views). ERROR shows as PENDING — still being checked."""
    if not customer_ids:
        return {}
    rows = db.execute(select(IdentityCheck.customer_id, IdentityCheck.status, IdentityCheck.created_at).where(
        IdentityCheck.customer_id.in_(set(customer_ids))).order_by(IdentityCheck.created_at)).all()
    out: dict[uuid.UUID, str] = {}
    for cid, status, _ in rows:  # ordered oldest → newest, so the last write wins
        out[cid] = "PENDING" if status == "ERROR" else status
    return out


def is_verified(db: Session, customer_id: uuid.UUID) -> bool:
    c = latest(db, customer_id)
    return bool(c and c.status == "VERIFIED")
