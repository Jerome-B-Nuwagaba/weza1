"""Resiliency spec v1.1: audit with client IP, MFA for all staff, notification backoff, dead-lettering and replay,
Infobip SMS, and k-anonymised preview reason signals."""

import uuid
from datetime import timedelta

import httpx
from sqlalchemy import select

from tests.helpers import idem, routed_to_lakeside
from weza.config import Settings
from weza.domains.identity.models import User
from weza.domains.institution.models import Institution
from weza.domains.misc_models import Notification
from weza.domains.notification import retry_queue
from weza.domains.notification import service as notify
from weza.domains.opportunity.models import Preview
from weza.domains.trust.models import AuditEvent
from weza.platform.db import session_scope, utcnow


def test_audit_rows_carry_actor_tenant_action_and_ip(client, as_user, journey):
    j, oid, owner = routed_to_lakeside(journey, "0772600001")
    h = {**as_user(owner), "X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
    client.post(f"/api/v1/inst/opportunities/{oid}/status", headers=idem(h), json={"state": "CONTACTED"})
    client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=idem(h),
                json={"kind": "QUESTION", "message": "How long have you traded?"})
    with session_scope() as db:
        rows = db.execute(select(AuditEvent).where(AuditEvent.action.in_(["opportunity.status",
                                                                          "info_request.created"]),
                                                   AuditEvent.ip == "203.0.113.7")).scalars().all()
        assert {r.action for r in rows} == {"opportunity.status", "info_request.created"}
        inst = db.execute(select(Institution).where(Institution.display_name == "Lakeside Bank")).scalar_one()
        user = db.execute(select(User).where(User.email == owner)).scalar_one()
        assert all(r.actor_id == str(user.id) and r.institution_id == inst.id for r in rows)


def test_mfa_enforced_for_institution_staff(client, monkeypatch):
    from weza.domains.identity import service as identity
    monkeypatch.setattr(identity, "get_settings", lambda: Settings(mfa_enforced=True))
    r = client.post("/api/v1/auth/login", json={"email": "officer2@lakeside.demo", "password": "WezaDemo!2026"})
    assert r.status_code == 200 and r.json().get("mfa_enrolment_required") is True and "access_token" not in r.json()


def _staff_note(db) -> Notification:
    user = db.execute(select(User).where(User.email == "manager@lakeside.demo")).scalar_one()
    n = Notification(event_type="Test", recipient_type="USER", recipient_id=user.id, channel="email",
                     title=f"Resiliency test {uuid.uuid4().hex[:6]}", body="b")
    db.add(n)
    db.flush()
    return n


def _failing_email(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("smtp down")
    monkeypatch.setattr(notify, "_send_email", boom)


def test_postgres_backoff_then_dead_letter_then_replay(client, as_user, monkeypatch):
    _failing_email(monkeypatch)
    with session_scope() as db:
        n = _staff_note(db)
        notify.deliver(db, n)
        assert n.status == "FAILED" and n.attempts == 1 and n.last_error == "smtp down"
        assert timedelta(seconds=50) < n.next_attempt_at - utcnow() <= timedelta(seconds=60)
        nid = n.id
    with session_scope() as db:
        notify.retry_sweep(db)  # not due yet — untouched
        assert db.get(Notification, nid).attempts == 1
        db.get(Notification, nid).next_attempt_at = utcnow() - timedelta(seconds=1)
    with session_scope() as db:
        notify.retry_sweep(db)
        n = db.get(Notification, nid)
        assert n.attempts == 2 and n.next_attempt_at - utcnow() > timedelta(seconds=250)  # second backoff: 5 min
        n.attempts, n.next_attempt_at = retry_queue.MAX_ATTEMPTS - 1, utcnow() - timedelta(seconds=1)
    with session_scope() as db:
        notify.retry_sweep(db)
        assert db.get(Notification, nid).status == "DEAD"
    ops = as_user("ops@weza.demo")
    failures = client.get("/api/v1/admin/deliveries", headers=ops).json()["notification_failures"]
    assert any(f["id"] == str(nid) and f["status"] == "DEAD" for f in failures)
    r = client.post(f"/api/v1/admin/notifications/{nid}/replay", headers=ops)
    assert r.status_code == 200 and r.json()["status"] == "FAILED"
    with session_scope() as db:
        assert db.get(Notification, nid).attempts == 0


def test_customer_sms_failure_never_breaks_the_transaction(monkeypatch):
    """Graceful fallback: the in-app notification is written even when the SMS gateway fails."""
    from weza.domains.customer.models import Customer
    monkeypatch.setattr(notify, "send_customer_message", lambda *a, **k: False)
    with session_scope() as db:
        cust = db.execute(select(Customer).limit(1)).scalar_one()
        notify.notify_customer(db, cust.id, "Test", title="Fallback check", body="b")
        assert db.execute(select(Notification).where(Notification.recipient_id == cust.id,
                                                     Notification.title == "Fallback check")).scalar_one()


def test_infobip_adapter(monkeypatch):
    monkeypatch.setattr(notify, "get_settings", lambda: Settings(
        sms_provider="infobip", infobip_base_url="xyz.api.infobip.com", infobip_api_key="k", infobip_sender="WEZA"))
    calls = []

    def fake_post(url, **kw):
        calls.append({"url": url, **kw})
        return httpx.Response(200, json={"messages": [{"status": {"groupName": "PENDING", "name": "PENDING_ENROUTE"}}]})
    monkeypatch.setattr(notify.httpx, "post", fake_post)
    assert notify._infobip_send("+256772000003", "Hi") is True
    assert calls[0]["url"] == "https://xyz.api.infobip.com/sms/2/text/advanced"
    assert calls[0]["headers"]["Authorization"] == "App k"
    assert calls[0]["json"]["messages"][0] == {"destinations": [{"to": "256772000003"}], "text": "Hi", "from": "WEZA"}
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kw: httpx.Response(
        200, json={"messages": [{"status": {"groupName": "REJECTED", "name": "REJECTED_DESTINATION"}}]}))
    assert notify._infobip_send("+256772000003", "Hi") is False
    assert "INFOBIP_BASE_URL" in " ".join(Settings(env="production", sms_provider="infobip").production_problems())


def test_preview_pass_reasons_are_structured_and_k_anonymised(client, as_user):
    h = as_user("business@lakeside.demo")
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == "Lakeside Bank")).scalar_one()
        ids = []
        for _ in range(6):
            p = Preview(need_id=uuid.uuid4(), match_id=uuid.uuid4(), institution_id=inst.id,
                        payload={"sector": "retail", "region": "Central", "customer_type": "SME"},
                        expires_at=utcnow() + timedelta(days=3))
            db.add(p)
            db.flush()
            ids.append(str(p.id))
    r = client.post(f"/api/v1/inst/previews/{ids[0]}/interest", headers=h, json={"state": "NOT_INTERESTED"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "REASON_REQUIRED"
    for pid in ids[:4]:
        assert client.post(f"/api/v1/inst/previews/{pid}/interest", headers=h,
                           json={"state": "NOT_INTERESTED", "reason": "TURNOVER_TOO_LOW"}).status_code == 200
    sig = client.get("/api/v1/inst/intelligence/reason-signals", headers=h).json()
    assert sig["total"] is None and sig["by_reason"] == {}  # under k: nothing shown
    client.post(f"/api/v1/inst/previews/{ids[4]}/interest", headers=h,
                json={"state": "NOT_INTERESTED", "reason": "TURNOVER_TOO_LOW"})
    client.post(f"/api/v1/inst/previews/{ids[5]}/interest", headers=h,
                json={"state": "NOT_INTERESTED", "reason": "OUTSIDE_REGION"})
    sig = client.get("/api/v1/inst/intelligence/reason-signals", headers=h).json()
    assert sig["total"] == 6 and sig["by_reason"] == {"Turnover / income too low": 5}  # the lone reason is dropped
    # Changing your mind removes the pass reason
    client.post(f"/api/v1/inst/previews/{ids[5]}/interest", headers=h, json={"state": "INTERESTED"})
    assert client.get("/api/v1/inst/intelligence/reason-signals", headers=h).json()["total"] == 5
