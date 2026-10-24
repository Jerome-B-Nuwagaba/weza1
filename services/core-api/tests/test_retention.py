"""Retention and privacy lifecycle (TSD §70). The engine decides RETAIN / DELETE / ANONYMISE from data type, purpose,
legal hold, policy and last activity; a dry run changes nothing; audit and commercial records are never touched."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from tests.helpers import routed_to_lakeside
from weza.domains.admin_config import RETENTION
from weza.domains.customer import documents as docs
from weza.domains.customer import service as customer_svc
from weza.domains.customer.models import Customer, Document, DocumentBlob, Fact
from weza.domains.identity import service as identity
from weza.domains.identity.models import OtpChallenge
from weza.domains.misc_models import ChannelMessage
from weza.domains.need.models import ConversationMessage
from weza.domains.opportunity.models import Opportunity
from weza.domains.trust import retention
from weza.domains.trust.models import AuditEvent
from weza.platform.db import session_scope, utcnow

PNG = b"\x89PNG\r\n\x1a\n" + b"retention-test-image" * 8


def make_customer(db, phone: str, idle_days: int) -> uuid.UUID:
    cust, _ = customer_svc.get_or_create_by_phone(db, phone)
    for key, value in (("identity.full_name", "Grace Retention"), ("identity.nin", "CM12345678RETN"),
                       ("business.name", "Retention Traders")):
        customer_svc.upsert_fact(db, cust.id, key, value, confirmed=True)
    docs.ingest(db, cust.id, doc_type="national_id", filename="id.png", declared_mime="image/png", data=PNG)
    cust.last_activity_at = utcnow() - timedelta(days=idle_days)
    db.flush()
    return cust.id


def test_the_default_policy_never_automates_legal_records():
    assert not set(RETENTION["rules"]) & set(retention.NEVER_AUTOMATED)
    # Even a policy that (wrongly) asks for it is refused: audit and commercial records follow their own lifecycle.
    bad = {"rules": {"audit_event": {"action": "DELETE", "after_days": 1}, "outcome": {"action": "ANONYMISE", "after_days": 1}}}
    assert retention._rule(bad, "audit_event") is None and retention._rule(bad, "outcome") is None
    assert retention._rule({"rules": {"x": {"action": "ARCHIVE", "after_days": 5}}}, "x") is None  # no archive store yet


def test_a_dry_run_changes_nothing_then_a_real_run_anonymises_an_idle_customer_once():
    phone = "+256772" + uuid.uuid4().hex[:6].translate(str.maketrans("abcdef", "123456"))
    with session_scope() as db:
        cid = make_customer(db, phone, idle_days=800)
        vault_token = db.get(Customer, cid).vault_token
    with session_scope() as db:
        preview = retention.run(db, apply=False)
        assert preview["applied"] is False and preview["customers"]["anonymise"] >= 1
        assert db.get(Customer, cid).status == "ACTIVE"
        assert identity.vault_read(db, vault_token)["phone"] == phone  # nothing was touched
        assert db.get(DocumentBlob, db.execute(select(Document.id).where(Document.customer_id == cid)).scalar_one())
    with session_scope() as db:
        retention.run(db, apply=True)
    with session_scope() as db:
        cust = db.get(Customer, cid)
        assert cust.status == "ANONYMISED" and cust.verification_level == "NONE"
        assert identity.vault_read(db, vault_token) == {"anonymised": True}  # phone and NIN are unrecoverable
        assert identity.vault_find_by_phone(db, phone) is None  # and the number no longer finds this record
        assert db.execute(select(func.count()).select_from(Fact).where(Fact.customer_id == cid)).scalar_one() == 0
        doc = db.execute(select(Document).where(Document.customer_id == cid)).scalar_one()
        assert doc.pipeline_state == "DELETED" and doc.sha256 and db.get(DocumentBlob, doc.id) is None  # hash is kept
        actions = set(db.execute(select(AuditEvent.action).where(AuditEvent.object_id == str(cid))).scalars())
        assert {"retention.customer_anonymised", "retention.document_deleted"} <= actions
    with session_scope() as db:  # idempotent: a second run has nothing left to do for this customer
        retention.run(db, apply=True)
        assert db.execute(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.object_id == str(cid), AuditEvent.action == "retention.customer_anonymised")).scalar_one() == 1


def test_between_the_two_periods_only_the_documents_go():
    phone = "+256773" + uuid.uuid4().hex[:6].translate(str.maketrans("abcdef", "123456"))
    with session_scope() as db:
        cid = make_customer(db, phone, idle_days=400)  # past the 365-day document period, inside the 730-day identity one
    with session_scope() as db:
        retention.run(db, apply=True)
    with session_scope() as db:
        cust = db.get(Customer, cid)
        assert cust.status == "ACTIVE" and identity.vault_read(db, cust.vault_token)["phone"] == phone
        assert db.execute(select(Document.pipeline_state).where(Document.customer_id == cid)).scalar_one() == "DELETED"
        assert db.execute(select(func.count()).select_from(Fact).where(Fact.customer_id == cid)).scalar_one() > 0


def test_a_legal_hold_keeps_everything(monkeypatch):
    phone = "+256774" + uuid.uuid4().hex[:6].translate(str.maketrans("abcdef", "123456"))
    with session_scope() as db:
        cid = make_customer(db, phone, idle_days=900)
    held = {**RETENTION, "legal_holds": [str(cid)]}
    monkeypatch.setattr(retention, "get_config", lambda db, key: (held, 9))
    with session_scope() as db:
        assert retention.customer_decision(db, db.get(Customer, cid), held, utcnow()) == ("RETAIN", "legal hold")
        retention.run(db, apply=True)
    with session_scope() as db:
        assert db.get(Customer, cid).status == "ACTIVE"
        assert db.execute(select(Document.pipeline_state).where(Document.customer_id == cid)).scalar_one() == "STORED"


def test_an_active_consent_or_open_opportunity_keeps_the_customers_data(journey):
    _, oid, _ = routed_to_lakeside(journey, "0772480001")
    with session_scope() as db:
        opp = db.get(Opportunity, uuid.UUID(oid))
        cust = db.get(Customer, opp.customer_id)
        cust.last_activity_at = utcnow() - timedelta(days=900)
        cid = cust.id
        decision = retention.customer_decision(db, cust, RETENTION, utcnow())
        assert decision[0] == "RETAIN" and decision[1] in ("active consent", "open opportunity")
        retention.run(db, apply=True)
    with session_scope() as db:
        assert db.get(Customer, cid).status == "ACTIVE"


def test_old_codes_and_message_text_are_cleaned_but_audit_is_never_touched():
    old = utcnow() - timedelta(days=400)
    with session_scope() as db:
        db.add(OtpChallenge(phone_index="p" * 64, code_hash="h" * 64, salt="s" * 32, expires_at=old, last_sent_at=old,
                            created_at=old))
        db.add(ChannelMessage(channel="sms", to_index="i" * 64, body="secret code 123456", payload={"kind": "otp"},
                              created_at=old))
        db.add(ConversationMessage(message_id=f"retention:{uuid.uuid4()}", session_id=uuid.uuid4(), channel="whatsapp",
                                   direction="IN", content={"type": "text", "text": "my private words"}, received_at=old))
        audit_before = db.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
    with session_scope() as db:
        report = retention.run(db, apply=True)
        assert report["rules"]["otp_challenge"]["done"] >= 1 and report["rules"]["channel_message"]["done"] >= 1
    with session_scope() as db:
        assert db.execute(select(func.count()).select_from(OtpChallenge).where(OtpChallenge.created_at <= old)).scalar_one() == 0
        assert db.execute(select(ChannelMessage.body).where(ChannelMessage.to_index == "i" * 64)).scalar_one() == "[redacted]"
        assert "my private words" not in str(db.execute(select(ConversationMessage.content).where(
            ConversationMessage.received_at <= old)).scalars().all())
        assert db.execute(select(func.count()).select_from(AuditEvent)).scalar_one() >= audit_before  # only ever added to


def test_only_super_admin_can_preview_or_run_retention(client, as_user):
    assert client.get("/api/v1/admin/retention").status_code == 401
    for email in ("ops@weza.demo", "commercial@weza.demo"):
        assert client.get("/api/v1/admin/retention", headers=as_user(email)).status_code == 403
    admin = as_user("admin@weza.demo")
    preview = client.get("/api/v1/admin/retention", headers=admin)
    assert preview.status_code == 200 and preview.json()["applied"] is False and "rules" in preview.json()
    assert client.post("/api/v1/admin/retention/run", headers=admin, json={"reason": "short"}).status_code == 422
    run = client.post("/api/v1/admin/retention/run", headers=admin, json={"reason": "Scheduled quarterly clean-up"})
    assert run.status_code == 200 and run.json()["applied"] is True
    with session_scope() as db:
        assert db.execute(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "retention.run_manual")).scalar_one() >= 1
