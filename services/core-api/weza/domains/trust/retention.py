"""Retention and privacy lifecycle (TSD §70, §71, §49).

For each kind of data the engine decides RETAIN, DELETE or ANONYMISE from its data type, purpose (an active consent or an
open opportunity), legal hold, the retention policy and the customer's last activity. The policy is country
configuration (`retention:UG`, versioned like every other configuration), so it changes without a release.

Safeguards, all deliberate:
- Audit events, the decision ledger, commercial events and reported outcomes are never touched by the engine: legally
  required audit/commercial retention follows its own lifecycle (TSD §70), whatever the policy says.
- A customer with an active consent, an open opportunity or a legal hold keeps their data.
- `run(apply=False)` changes nothing and reports exactly what a real run would do.
- Identity is anonymised, not merely hidden: the encrypted record is replaced and its lookup indexes are cleared, so the
  phone number and National ID can no longer be found or recovered.
- ARCHIVE is not performed: WEZA has no archive store yet, so an ARCHIVE rule is reported as RETAIN.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from weza.domains.admin_config import get_config
from weza.domains.consent.models import Consent
from weza.domains.customer.models import Customer, Document, DocumentBlob, Fact, ProfileSnapshot
from weza.domains.identity.models import OtpChallenge, VaultRecord
from weza.domains.misc_models import ChannelMessage
from weza.domains.need.models import ConversationMessage
from weza.domains.opportunity.models import Opportunity
from weza.domains.trust.service import audit
from weza.platform import crypto
from weza.platform.context import Actor
from weza.platform.db import utcnow
from weza.platform.models import RateCounter

RETAIN, DELETE, ANONYMISE = "RETAIN", "DELETE", "ANONYMISE"
#: Kept for legal reasons on their own lifecycle; the engine refuses to act on them even if a policy says to.
NEVER_AUTOMATED = ("audit_event", "decision", "commercial_event", "outcome")
SYSTEM = Actor(kind="SYSTEM", display="Retention engine")
REDACTED = {"type": "redacted"}
BATCH = 500  # customers handled per run, so one run never holds a long transaction


def _rule(pol: dict, name: str) -> dict | None:
    """The rule for `name` if it is an automated DELETE/ANONYMISE with a period, else None."""
    if name in NEVER_AUTOMATED:
        return None
    r = (pol.get("rules") or {}).get(name)
    return r if r and r.get("action") in (DELETE, ANONYMISE) and int(r.get("after_days") or 0) > 0 else None


def _cutoff(rule: dict, now: datetime) -> datetime:
    return now - timedelta(days=int(rule["after_days"]))


def customer_decision(db: Session, cust: Customer, pol: dict, now: datetime) -> tuple[str, str]:
    """RETAIN, DELETE (their documents only) or ANONYMISE (their identity and profile), with the reason."""
    from weza.domains.opportunity.service import OPEN_STATES
    if str(cust.id) in {str(x) for x in pol.get("legal_holds") or []}:
        return RETAIN, "legal hold"
    if cust.status == "ANONYMISED":
        return RETAIN, "already anonymised"
    if db.execute(select(func.count()).select_from(Consent).where(Consent.customer_id == cust.id,
                                                                  Consent.status == "GRANTED")).scalar_one():
        return RETAIN, "active consent"
    if db.execute(select(func.count()).select_from(Opportunity).where(Opportunity.customer_id == cust.id,
                                                                      Opportunity.state.in_(OPEN_STATES))).scalar_one():
        return RETAIN, "open opportunity"
    identity, files = _rule(pol, "customer_identity"), _rule(pol, "document_file")
    if identity and cust.last_activity_at < _cutoff(identity, now):
        return ANONYMISE, f"no activity for {identity['after_days']} days"
    if files and cust.last_activity_at < _cutoff(files, now):
        return DELETE, f"no activity for {files['after_days']} days (documents)"
    return RETAIN, "within retention"


def delete_documents(db: Session, cust: Customer, reason: str) -> int:
    """Remove the stored files (never the metadata, hash or the fact that a document was supplied)."""
    n = 0
    for doc in db.execute(select(Document).where(Document.customer_id == cust.id)).scalars():
        if db.get(DocumentBlob, doc.id) is None:
            continue
        db.execute(delete(DocumentBlob).where(DocumentBlob.document_id == doc.id))
        doc.pipeline_state, doc.extracted = "DELETED", None
        audit(db, SYSTEM, "retention.document_deleted", "document", doc.id, reason=reason,
              after={"doc_type": doc.doc_type, "classification": doc.classification})
        n += 1
    return n


def anonymise_customer(db: Session, cust: Customer, reason: str) -> None:
    """Identity lifecycle: documents, encrypted identifiers, profile facts and message text are removed."""
    delete_documents(db, cust, reason)
    vault = db.get(VaultRecord, cust.vault_token)
    if vault is not None:
        vault.ciphertext, vault.wrapped_key = crypto.encrypt_record({"anonymised": True})
        vault.phone_index = crypto.sha256_hex(f"anonymised:{vault.id}")  # still unique; matches no real number
        vault.nin_index, vault.phone_last4 = None, ""
    db.execute(delete(Fact).where(Fact.customer_id == cust.id))
    db.execute(delete(ProfileSnapshot).where(ProfileSnapshot.customer_id == cust.id))
    db.execute(update(ConversationMessage).where(ConversationMessage.customer_id == cust.id).values(content=REDACTED))
    cust.status, cust.device_hash, cust.verification_level = "ANONYMISED", None, "NONE"
    audit(db, SYSTEM, "retention.customer_anonymised", "customer", cust.id, reason=reason)


def run(db: Session, *, apply: bool = False, now: datetime | None = None) -> dict:
    """Evaluate the policy; with apply=True also carry it out. Idempotent: a second run finds nothing left to do."""
    now = now or utcnow()
    pol, version = get_config(db, "retention:UG")
    report: dict = {"policy_version": version, "applied": apply, "rules": {}, "customers": {}}

    def record(name: str, rule: dict, eligible: int, done: int = 0) -> None:
        report["rules"][name] = {"action": rule["action"], "after_days": rule["after_days"], "eligible": eligible,
                                 "done": done if apply else 0}

    if rule := _rule(pol, "otp_challenge"):
        q = OtpChallenge.created_at < _cutoff(rule, now)
        n = db.execute(select(func.count()).select_from(OtpChallenge).where(q)).scalar_one()
        record("otp_challenge", rule, n, db.execute(delete(OtpChallenge).where(q)).rowcount if apply and n else 0)
    if rule := _rule(pol, "rate_counter"):
        q = RateCounter.window_start < _cutoff(rule, now)
        n = db.execute(select(func.count()).select_from(RateCounter).where(q)).scalar_one()
        record("rate_counter", rule, n, db.execute(delete(RateCounter).where(q)).rowcount if apply and n else 0)
    if rule := _rule(pol, "channel_message"):
        q = (ChannelMessage.created_at < _cutoff(rule, now)) & (ChannelMessage.body != "[redacted]")
        n = db.execute(select(func.count()).select_from(ChannelMessage).where(q)).scalar_one()
        done = db.execute(update(ChannelMessage).where(q).values(body="[redacted]", payload={"redacted": True})
                          ).rowcount if apply and n else 0
        record("channel_message", rule, n, done)
    if rule := _rule(pol, "conversation_message"):
        q = (ConversationMessage.received_at < _cutoff(rule, now)) & (ConversationMessage.content != REDACTED)
        n = db.execute(select(func.count()).select_from(ConversationMessage).where(q)).scalar_one()
        done = db.execute(update(ConversationMessage).where(q).values(content=REDACTED)).rowcount if apply and n else 0
        record("conversation_message", rule, n, done)

    # Customers: identity first, then their stored documents; everyone else is reported with the reason they stay.
    horizon = [_cutoff(r, now) for r in (_rule(pol, "customer_identity"), _rule(pol, "document_file")) if r]
    counts = {"anonymise": 0, "documents": 0, "retained": {}}
    if horizon:
        stale = db.execute(select(Customer).where(Customer.last_activity_at < max(horizon), Customer.status != "ANONYMISED")
                           .order_by(Customer.last_activity_at).limit(BATCH)).scalars().all()
        for cust in stale:
            decision, why = customer_decision(db, cust, pol, now)
            if decision == ANONYMISE:
                counts["anonymise"] += 1
                if apply:
                    anonymise_customer(db, cust, why)
            elif decision == DELETE:
                counts["documents"] += 1
                if apply:
                    delete_documents(db, cust, why)
            else:
                counts["retained"][why] = counts["retained"].get(why, 0) + 1
    report["customers"] = counts
    report["never_automated"] = list(NEVER_AUTOMATED)
    if apply:
        audit(db, SYSTEM, "retention.run", "retention", "scheduled",
              after={"policy_version": version, "rules": {k: v["done"] for k, v in report["rules"].items()},
                     "customers_anonymised": counts["anonymise"], "customers_documents_deleted": counts["documents"]})
    return report
