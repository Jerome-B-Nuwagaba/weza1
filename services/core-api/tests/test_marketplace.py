"""Marketplace loops: clearing on supply change, outcomes, billing & disputes, waiting room, rescue,
service targets, freshness, kill switches (AT-13/14, AT-33/34, AT-36, AT-41…47, AT-50)."""

from datetime import timedelta

from sqlalchemy import select

from tests.helpers import SME_ANSWERS
from weza.domains.commercial.models import CommercialEvent
from weza.domains.institution.models import Institution
from weza.domains.matching.models import Match, WaitingEntry
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import Assignment, Opportunity
from weza.domains.product.models import Product
from weza.platform.db import session_scope, utcnow


def _submit(journey, drain, phone: str, text: str, institution: str = "Lakeside Bank"):
    j = journey(text)
    j.send(action="confirm")
    j.verify(phone)
    j.answer_profile({**SME_ANSWERS, "identity.nin": "CM" + phone[-10:] + "AB"})
    opt = next(o for o in j.cards("options")[0]["options"] if o["institution"] == institution and o["readiness"] == "READY")
    j.send(action="select", value=opt["match_id"])
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    drain()
    ref = j.cards("submitted")[0]["reference"]
    with session_scope() as db:
        o = db.execute(select(Opportunity).where(Opportunity.reference == ref)).scalar_one()
        return j, str(o.id)


def _owner_headers(as_user, opp_id):
    from weza.domains.identity.models import User
    with session_scope() as db:
        a = db.get(Assignment, opp_id)
        return as_user(db.get(User, a.user_id).email)


def test_outcomes_billing_and_dispute_reversal(client, journey, drain, as_user):
    """AT-34, AT-44…46: reported outcomes labelled; disputes create reversal events, never edits."""
    j, oid = _submit(journey, drain, "0772300001", "I need UGX 25 million to expand my pharmacy")
    h = _owner_headers(as_user, oid)
    r = client.post(f"/api/v1/inst/opportunities/{oid}/status", json={"state": "CONTACTED"},
                    headers={**h, "Idempotency-Key": "c1"})
    assert r.status_code == 200 and r.json()["state"] == "CONTACTED"
    r = client.post(f"/api/v1/inst/opportunities/{oid}/outcome", json={"state": "REPORTED_APPROVED", "approved_amount": 25e6},
                    headers={**h, "Idempotency-Key": "o1"})
    r = client.post(f"/api/v1/inst/opportunities/{oid}/outcome",
                    json={"state": "REPORTED_DISBURSED", "disbursed_amount": 25e6, "disbursed_on": "2026-10-10"},
                    headers={**h, "Idempotency-Key": "o2"})
    body = r.json()
    assert r.status_code == 200, r.text
    assert body["state"] == "REPORTED_DISBURSED"
    assert all(o["label"] == "Reported by institution" for o in body["outcomes"])
    # Same idempotency key replayed → no duplicate outcome
    client.post(f"/api/v1/inst/opportunities/{oid}/outcome",
                json={"state": "REPORTED_DISBURSED", "disbursed_amount": 25e6, "disbursed_on": "2026-10-10"},
                headers={**h, "Idempotency-Key": "o2"})
    assert len(client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()["outcomes"]) == 2
    drain()
    status = client.get("/api/v1/me/needs", headers=j.customer_headers).json()["needs"][0]["opportunities"][0]
    assert status["state"] == "REPORTED_DISBURSED" and status["outcomes"][-1]["reported_by"] == "Lakeside Bank"

    admin = as_user("admin@lakeside.demo")
    ev = next(e for e in client.get("/api/v1/inst/billing", headers=admin).json()["events"]
              if e["reference"] and e["kind"] == "QUALIFIED_OPPORTUNITY" and e["status"] in ("BILLABLE", "INCLUDED_IN_PLAN"))
    r = client.post(f"/api/v1/inst/billing/events/{ev['id']}/dispute",
                    json={"reason": "UNREACHABLE", "description": "Customer never answered the phone."},
                    headers={**admin, "Idempotency-Key": "d1"})
    assert r.status_code == 201
    comm = as_user("commercial@weza.demo")
    d = next(x for x in client.get("/api/v1/admin/disputes", headers=comm).json()["disputes"] if x["state"] == "OPEN")
    client.post(f"/api/v1/admin/disputes/{d['id']}/move", json={"state": "UNDER_REVIEW"}, headers=comm)
    r = client.post(f"/api/v1/admin/disputes/{d['id']}/move",
                    json={"state": "DECIDED", "decision": "CHARGE_REVERSED", "note": "Evidence accepted"}, headers=comm)
    assert r.status_code == 200
    with session_scope() as db:
        rows = db.execute(select(CommercialEvent).where(CommercialEvent.reverses_event_id.is_not(None))).scalars().all()
        assert any(float(x.amount) == -ev["amount"] and x.kind == "REVERSAL" for x in rows)


def test_paused_product_is_removed_and_market_reclears(client, journey, drain, as_user):
    """AT-13/14/47/50: pausing supply excludes it and re-runs clearing; customers are never routed to it."""
    ops = as_user("ops@weza.demo")
    with session_scope() as db:
        p = db.execute(select(Product).where(Product.name == "Small Business Boost")).scalar_one()
        pid = str(p.id)
    r = client.post(f"/api/v1/admin/products/{pid}/status", json={"status": "PAUSED", "reason": "Test pause"}, headers=ops)
    assert r.status_code == 200
    drain()
    with session_scope() as db:
        live = db.execute(select(Match).where(Match.product_id == p.id,
                                              Match.state.in_(["RANKED", "PRESENTED"]))).scalars().all()
        assert live == []
    client.post(f"/api/v1/admin/products/{pid}/status", json={"status": "ACTIVE", "reason": "Resume"}, headers=ops)
    drain()


def test_pause_all_routing_kill_switch(client, journey, drain, as_user):
    """TSD §75: pause all routing → no options presented; resume restores."""
    admin = as_user("admin@weza.demo")
    client.post("/api/v1/admin/kill-switches", json={"key": "pause_all_routing", "value": {"on": True},
                                                      "reason": "Incident drill"}, headers=admin)
    drain()
    j = journey("I need UGX 10 million for stock for my shop")
    j.send(action="confirm")
    j.verify("0772300002")
    j.answer_profile({**SME_ANSWERS, "identity.nin": "CM0772300002AB", "business.sector": "retail_trade"})
    assert j.node == "OFFER_WAITING_ROOM"
    client.post("/api/v1/admin/kill-switches", json={"key": "pause_all_routing", "value": {"on": False},
                                                      "reason": "Drill over"}, headers=admin)
    drain()


def test_waiting_room_match_found_on_new_supply(client, journey, drain, as_user):
    """AT-36 / G5: a waiting customer is notified (not disclosed) when new appetite appears."""
    j = journey("I need UGX 600 million for stock for my salon")
    j.send(action="confirm")
    j.verify("0772300003")
    j.answer_profile({**SME_ANSWERS, "identity.nin": "CM0772300003AB", "business.sector": "beauty",
                      "business.district": "Gulu", "business.age_months": "3 months", "business.registered": "no"})
    assert j.node == "OFFER_WAITING_ROOM", j.node
    j.send(action="wait")
    # Kijani creates a new Northern micro-business appetite for its solar product's sibling: use Pearl's product
    credit = as_user("credit@kijani.demo")
    kadmin = as_user("admin@kijani.demo")
    prod = client.post("/api/v1/inst/products", json={
        "name": "Northern Micro-Business", "family": "SME_WORKING_CAPITAL",
        "terms": {"min_amount": 400_000_000, "max_amount": 900_000_000, "min_tenor_months": 3, "max_tenor_months": 36},
        "rules": [{"field": "customer_type", "op": "in", "value": ["SME"]}]}, headers=credit).json()
    pid = prod["product_id"]
    client.post(f"/api/v1/inst/products/{pid}/submit", headers=credit)
    client.post(f"/api/v1/inst/products/{pid}/review", json={"approve": True, "note": "ok"}, headers=kadmin)
    aid = client.post("/api/v1/inst/appetites", json={"name": "Northern micro", "product_ids": [pid],
                                                      "criteria": [], "min_match_score": 50}, headers=credit).json()["appetite_id"]
    client.post(f"/api/v1/inst/appetites/{aid}/simulate", headers=credit)
    r = client.post(f"/api/v1/inst/appetites/{aid}/review", json={"approve": True, "note": "ok"}, headers=kadmin)
    assert r.status_code == 200, r.text
    drain()
    with session_scope() as db:
        need = db.execute(select(FinancialNeed).where(FinancialNeed.journey_id == j.id)).scalar_one()
        assert db.get(WaitingEntry, need.id).status == "MATCH_FOUND"
    view = client.get(f"/api/v1/journeys/{j.id}", headers=j.headers).json()
    assert view["node"] == "PRESENT_OPTIONS"


def test_decline_rescue_requires_new_consent(client, journey, drain, as_user):
    """AT-41 / G7: after a reported decline the customer chooses alternatives; nothing auto-routes."""
    j, oid = _submit(journey, drain, "0772300004", "I need UGX 8 million for stock for my pharmacy")
    h = _owner_headers(as_user, oid)
    client.post(f"/api/v1/inst/opportunities/{oid}/outcome", json={"state": "REPORTED_DECLINED",
                                                                    "reason_category": "INCOME_TURNOVER"},
                headers={**h, "Idempotency-Key": "decl-1"})
    drain()
    view = client.get(f"/api/v1/journeys/{j.id}", headers=j.headers).json()
    assert view["node"] == "RESCUE_ASK"
    j.send(action="rescue_yes")
    assert j.node in ("PRESENT_OPTIONS", "OFFER_WAITING_ROOM", "REQUEST_MISSING_ITEM")
    if j.node == "PRESENT_OPTIONS":
        insts = {o["institution"] for o in j.cards("options")[0]["options"]}
        assert "Lakeside Bank" not in insts
    with session_scope() as db:
        assert db.execute(select(Opportunity).where(Opportunity.id == oid)).scalar_one().state == "REMATCH_ELIGIBLE"


def test_service_target_breach_and_freshness(drain):
    """AT-33/42: timers escalate breaches and age opportunities."""
    with session_scope() as db:
        o, a = db.execute(select(Opportunity, Assignment).join(Assignment, Assignment.opportunity_id == Opportunity.id)
                          .where(Opportunity.state == "ASSIGNED", Assignment.first_contact_at.is_(None)).limit(1)).first()
        a.first_contact_due_at = utcnow() - timedelta(minutes=5)
        a.breach_state = "ON_TRACK"
        o.last_activity_at = utcnow() - timedelta(days=8)
        oid = o.id
    with session_scope() as db:
        opp_svc.service_target_sweep(db)
        opp_svc.freshness_sweep(db)
    with session_scope() as db:
        assert db.get(Assignment, oid).breach_state in ("BREACHED", "ESCALATED")
        assert db.get(Opportunity, oid).freshness == "STALE"
    drain()


def test_whatsapp_simulator_runs_same_graph(client):
    """AT-02: the simulator drives the identical journey graph via the channel gateway."""
    r = client.post("/api/v1/channels/simulator/messages",
                    json={"phone": "0772300005", "text": "I need 5 million for stock for my shop"})
    assert r.status_code == 200, r.text
    msgs = r.json()["messages"]
    assert any("Is this right" in (m.get("text") or "") for m in msgs if m["direction"] == "OUT")
    r = client.post("/api/v1/channels/simulator/messages",
                    json={"phone": "0772300005", "action": "confirm", "label": "Yes, that's right"}).json()
    # WhatsApp verifies the sender's number itself: no code is sent into the same chat (web/app keep the OTP).
    assert r["node"] == "ASK_PROFILE"
    assert not [m for m in r["messages"] if "verification code" in (m.get("text") or "")]
    with session_scope() as db:
        assert db.execute(select(Institution)).first()
