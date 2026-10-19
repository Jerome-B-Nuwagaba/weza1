"""Regression checks for transactional requests, UTC boundaries, and tenant analytics."""
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.helpers import idem, opp_for, routed_to_lakeside
from weza.domains.opportunity import service as opportunity
from weza.domains.opportunity.models import Assignment, InfoRequest, Opportunity, Outcome
from weza.platform.db import session_scope, utcnow
from weza.platform.models import OutboxEvent


def test_team_contact_rate_uses_exact_30_day_window(client, as_user, monkeypatch):
    from weza.api.v1 import institution
    now = datetime(2099, 1, 31, 12, tzinfo=UTC)
    monkeypatch.setattr(institution, "utcnow", lambda: now)
    oid, _ = opp_for("Lakeside Bank")
    created = []
    with session_scope() as db:
        source = db.get(Opportunity, uuid.UUID(oid))
        owner = db.get(Assignment, source.id).user_id
        tenant = source.institution_id
        # One recent, one exactly at the boundary, one just outside, and one in the future.
        for when in (now - timedelta(days=2), now - timedelta(days=30),
                     now - timedelta(days=30, seconds=1), now + timedelta(seconds=1)):
            item = Opportunity(reference="T-" + uuid.uuid4().hex[:10], idempotency_key=str(uuid.uuid4()),
                               need_id=source.need_id, customer_id=source.customer_id, institution_id=tenant,
                               product_id=source.product_id, match_id=source.match_id, consent_id=source.consent_id,
                               state="CONTACTED", amount=1, match_score=50, qualified_at=when)
            db.add(item)
            db.flush()
            db.add(Assignment(opportunity_id=item.id, institution_id=tenant, user_id=owner,
                              assigned_at=when, first_contact_at=when))
            created.append(item.id)
    try:
        r = client.get("/api/v1/inst/team", headers=as_user("manager@lakeside.demo"))
        assert r.status_code == 200, r.text
        member = next(m for m in r.json()["members"] if m["id"] == str(owner))
        assert member["contacted"] == 2
        assert member["assigned_30d"] == 2
        assert member["contact_rate"] == 100
    finally:
        with session_scope() as db:
            for oid in created:
                db.delete(db.get(Assignment, oid))
                db.delete(db.get(Opportunity, oid))


def test_terms_expire_on_utc_date_at_eat_midnight(monkeypatch):
    # 00:30 in Kampala is still the preceding UTC date.
    monkeypatch.setattr(opportunity, "utcnow", lambda: datetime(2026, 10, 18, 21, 30, tzinfo=UTC))
    terms = Outcome(terms_valid_until=date(2026, 10, 18))
    assert opportunity.outcome_terms(terms)["expired"] is False
    monkeypatch.setattr(opportunity, "utcnow", lambda: datetime(2026, 10, 19, 0, 0, tzinfo=UTC))
    assert opportunity.outcome_terms(terms)["expired"] is True


def test_expired_request_cannot_be_answered_before_worker_sweep(client, as_user, journey):
    j, oid, owner = routed_to_lakeside(journey, "0772583001")
    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=idem(as_user(owner)),
                    json={"kind": "QUESTION", "message": "How many staff?"})
    assert r.status_code == 201, r.text
    rid = r.json()["info_requests"][0]["id"]
    with session_scope() as db:
        db.get(InfoRequest, uuid.UUID(rid)).due_at = utcnow() - timedelta(seconds=1)
    r = client.post(f"/api/v1/me/info-requests/{rid}/respond", headers=j.customer_headers,
                    json={"response_text": "Four"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_OPEN"
    with session_scope() as db:
        assert db.get(InfoRequest, uuid.UUID(rid)).response_text is None
        assert not db.execute(select(OutboxEvent.id).where(OutboxEvent.event_type == "InfoRequestFulfilled",
                                                          OutboxEvent.data["request_id"].astext == rid)).first()


def test_request_and_outbox_roll_back_together(client, as_user, journey, monkeypatch):
    _, oid, owner = routed_to_lakeside(journey, "0772583002")
    original = opportunity.emit
    def fail_after_event(db, event_type, **kwargs):
        result = original(db, event_type, **kwargs)
        if event_type == "InfoRequested":
            db.flush()
            raise RuntimeError("simulated transaction failure")
        return result
    monkeypatch.setattr(opportunity, "emit", fail_after_event)
    with pytest.raises(RuntimeError, match="simulated transaction failure"):
        client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=idem(as_user(owner)),
                    json={"kind": "QUESTION", "message": "Atomic request regression"})
    with session_scope() as db:
        assert not db.execute(select(InfoRequest.id).where(InfoRequest.opportunity_id == uuid.UUID(oid))).first()
        assert not db.execute(select(OutboxEvent.id).where(OutboxEvent.aggregate_id == oid,
                                                          OutboxEvent.event_type == "InfoRequested")).first()


def test_info_status_is_database_constrained(client, as_user, journey):
    import sqlalchemy as sa
    _, oid, owner = routed_to_lakeside(journey, "0772583003")
    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=idem(as_user(owner)),
                    json={"kind": "QUESTION", "message": "When can we call?"})
    assert r.status_code == 201, r.text
    rid = r.json()["info_requests"][0]["id"]
    with pytest.raises(sa.exc.DataError):
        with session_scope() as db:
            db.execute(sa.text("UPDATE opportunity.info_request SET status='UNKNOWN' WHERE id=:id"), {"id": rid})
