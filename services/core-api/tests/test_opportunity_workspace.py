"""Goal 5 — the institution-officer experience of a routed opportunity.

The end-to-end path: a demo customer states a need, verifies their phone, is matched, consents, and is routed to
Demo Bank; Demo Bank's officer sees it in their own queue, reads what was shared and why, records the statuses and
reports the outcome. WEZA records — it never decides, and it never moves money.

Demo Bank is built through the real institution services, so the officer here is a real, ACTIVE lender's officer
rather than a fixture.
"""

import uuid

import pytest
from sqlalchemy import select

from tests.helpers import SME_ANSWERS
from tests.helpers import idem as _k
from weza.domains.opportunity.models import Activity, Assignment, Opportunity
from weza.domains.trust.models import AuditEvent
from weza.platform.db import session_scope
from weza.seed import seed_demo_bank

# No National ID: the bureau check is Just-In-Time and belongs to the lender's stage, so this journey never
# triggers one.
DEMO_ANSWERS = {**SME_ANSWERS, "identity.nin": "skip"}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
OFFICER = "officer@demo.bank"


@pytest.fixture(scope="module")
def demo_bank():
    """Demo Bank — one ACTIVE product and one ACTIVE mandate, routed to its own SME desk."""
    with session_scope() as db:
        state = seed_demo_bank(db)
        return {"id": str(state["inst"].id), "name": state["inst"].display_name}


def _routed_to_demo_bank(journey, phone: str, text: str):
    """A customer journey that ends with a consented opportunity routed to Demo Bank."""
    j = journey(text)
    j.send(action="confirm")
    j.verify(phone)
    j.answer_profile(DEMO_ANSWERS)
    demo = next(o for o in j.cards("options")[0]["options"] if o["institution"] == "Demo Bank")
    j.send(action="select", value=demo["match_id"])
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    reference = j.cards("submitted")[0]["reference"]
    return j, reference


def _opp(reference: str):
    with session_scope() as db:
        opp = db.execute(select(Opportunity).where(Opportunity.reference == reference)).scalar_one()
        return opp.id


def test_the_officer_works_a_routed_opportunity_from_queue_to_reported_disbursement(
        client, as_user, journey, drain, demo_bank):
    """Demo customer → verified → matched → consented → routed to Demo Bank → the officer views it, records the
    statuses and reports the outcome. Nothing is decided or paid by WEZA."""
    j, reference = _routed_to_demo_bank(journey, "0772400101", "I need UGX 30 million to expand my pharmacy")
    drain()
    oid = _opp(reference)
    h = as_user(OFFICER)

    # ---- the queue: the opportunity is in the officer's own work, not in someone else's
    feed = client.get("/api/v1/inst/opportunities?view=mine", headers=h).json()
    assert any(i["reference"] == reference for i in feed["items"]), feed["items"]
    day = client.get("/api/v1/inst/my-day", headers=h).json()
    assert any(i["reference"] == reference for i in day["sections"]["new"]), day["counts"]

    # ---- the detail: what was shared, why, and under what consent
    view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
    assert view["reference"] == reference
    assert view["amount"] > 0
    assert view["need"] and view["purpose_category"]  # what the customer asked for
    assert view["match_score"] > 0 and view["quality_score"] > 0  # explainable scores
    assert view["why_matched"] and view["components"]  # why it matched, component by component
    assert view["consent"]["status"] == "GRANTED"
    assert view["consent"]["categories"]
    assert view["customer"]["restricted"] is False  # the assigned officer sees the customer
    assert view["customer"]["fields"]["full_name"] == "Grace Nakato"
    assert "documents" in view["customer"]  # the documents shared with this institution
    assert view["owner"] == "Isaac Lukwago"
    assert view["state"] in ("ROUTED", "ASSIGNED")
    # The officer's status ladder, with the status they are on now
    assert [s["label"] for s in view["status_ladder"]] == [
        "New", "Assigned", "Contacted", "More information requested", "Customer proceeding",
        "In institution review", "Approved", "Declined", "Disbursed reported"]

    # ---- an internal note: the institution's own record, never the customer's
    note = client.post(f"/api/v1/inst/opportunities/{oid}/note", headers=h,
                       json={"note": "Called the customer; turnover statements to follow on Monday."})
    assert note.status_code == 200, note.text
    assert any(a["kind"] == "NOTE" for a in note.json()["activity"])

    # ---- the statuses the officer records
    contacted = client.post(f"/api/v1/inst/opportunities/{oid}/status", headers=_k(h),
                            json={"state": "CONTACTED", "note": "Called and introduced the offer."})
    assert contacted.status_code == 200, contacted.text
    assert contacted.json()["state"] == "CONTACTED"

    # More information requested — the officer asks through WEZA, then records the status
    asked = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=_k(h), json={
        "kind": "DOCUMENT", "doc_type": "bank_statement", "message": "Please share 6 months of bank statements."})
    assert asked.status_code == 201, asked.text
    body = asked.json()
    # The ask itself does not move the opportunity: the officer records the statuses they have reached.
    assert body["state"] == "CONTACTED"
    assert body["awaiting_customer"] is True
    more = client.post(f"/api/v1/inst/opportunities/{oid}/status", headers=_k(h),
                       json={"state": "INFORMATION_REQUESTED", "note": "Asked for 6 months of statements."})
    assert more.status_code == 200, more.text
    body = more.json()
    assert body["state"] == "INFORMATION_REQUESTED"
    assert body["status_ladder"][3]["current"] is True
    assert body["next_states"] == ["PROCEEDING", "SUBMITTED_TO_INSTITUTION"]

    # The customer answers, and the document they were asked for becomes available to the officer
    drain()
    mine = client.get("/api/v1/me/info-requests", headers=j.customer_headers).json()
    assert mine["open"] == 1
    doc = client.post("/api/v1/me/documents", headers=j.customer_headers, data={"doc_type": "bank_statement"},
                      files={"file": ("statement.pdf", PDF, "application/pdf")}).json()
    answered = client.post(f"/api/v1/me/info-requests/{mine['requests'][0]['id']}/respond",
                           headers=j.customer_headers, json={"document_id": doc["id"]})
    assert answered.status_code == 200, answered.text
    drain()
    view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
    assert any(d["id"] == doc["id"] for d in view["customer"]["documents"])
    assert client.get(f"/api/v1/inst/opportunities/{oid}/documents/{doc['id']}", headers=h).status_code == 200

    # In institution review
    review = client.post(f"/api/v1/inst/opportunities/{oid}/status", headers=_k(h),
                         json={"state": "SUBMITTED_TO_INSTITUTION", "note": "File complete."})
    assert review.status_code == 200, review.text
    assert review.json()["state"] == "SUBMITTED_TO_INSTITUTION"

    # ---- the outcome: the institution's own decision, reported back
    approved = client.post(f"/api/v1/inst/opportunities/{oid}/outcome", headers=_k(h), json={
        "state": "REPORTED_APPROVED", "approved_amount": 30_000_000, "tenor_months": 24})
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["state"] == "REPORTED_APPROVED"
    assert body["outcomes"][0]["label"] == "Reported by institution"

    # No disbursement destination: the amount and the date are reported, never a place to send money
    disbursed = client.post(f"/api/v1/inst/opportunities/{oid}/outcome", headers=_k(h), json={
        "state": "REPORTED_DISBURSED", "disbursed_amount": 30_000_000, "disbursed_on": "2026-10-30",
        "disbursement_destination": "0772400101"})
    assert disbursed.status_code == 200, disbursed.text
    body = disbursed.json()
    assert body["state"] == "REPORTED_DISBURSED"
    assert "disbursement_destination" not in body["outcomes"][-1]
    assert "0772400101" not in str(body["outcomes"][-1])

    # ---- every status change is audited, with the officer who made it
    with session_scope() as db:
        rows = db.execute(select(AuditEvent).where(
            AuditEvent.object_type == "opportunity", AuditEvent.object_id == str(oid)).order_by(AuditEvent.at)).scalars()
        actions = [(r.action, (r.after or {}).get("state"), r.actor_display) for r in rows]
    states = [s for a, s, _ in actions if a == "opportunity.status"]
    assert states == ["CONTACTED", "INFORMATION_REQUESTED", "SUBMITTED_TO_INSTITUTION", "REPORTED_APPROVED",
                      "REPORTED_DISBURSED"]
    assert any(a == "opportunity.note_added" for a, _, _ in actions)
    assert any(a == "opportunity.routed" for a, _, _ in actions)
    assert all("Isaac Lukwago" in (who or "") for a, s, who in actions if a == "opportunity.status")

    # ---- the customer sees the status trail and the institution-reported outcome, but no internal note
    needs = client.get("/api/v1/me/needs", headers=j.customer_headers).json()["needs"]
    mine_opp = next(o for o in needs[0]["opportunities"] if o["reference"] == reference)
    assert mine_opp["state"] == "REPORTED_DISBURSED"
    assert [t["label"] for t in mine_opp["timeline"] if t["state"] == "INFORMATION_REQUESTED"] == [
        "The institution has asked you for more information"]
    assert not any("turnover statements" in json_text for json_text in
                   [str(mine_opp), str(needs)])


def test_an_officer_never_sees_another_institutions_opportunity(client, as_user, journey, drain, demo_bank):
    """Institution isolation: the opportunity is invisible — a 404, not a permission error — to anyone else."""
    _j, reference = _routed_to_demo_bank(journey, "0772400102", "I need UGX 20 million for stock in my pharmacy")
    drain()
    oid = _opp(reference)

    for email in ("officer@lakeside.demo", "manager@pearl.demo", "admin@lakeside.demo"):
        h = as_user(email)
        assert client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).status_code == 404, email
        # …and their queue does not contain it either
        assert not any(i["id"] == str(oid) for i in client.get("/api/v1/inst/opportunities?view=all", headers=h).json()["items"])


def test_an_officer_cannot_work_an_opportunity_assigned_to_someone_else(client, as_user, journey, drain, demo_bank):
    """Within their own institution, an officer acts only on the work assigned to them."""
    _j, reference = _routed_to_demo_bank(journey, "0772400103", "I need UGX 26 million for pharmacy stock")
    drain()
    oid = _opp(reference)
    with session_scope() as db:
        assigned = db.get(Assignment, oid)
        assert assigned.user_id is not None

    # A second Demo Bank officer, created for this test only
    from weza.domains.identity import service as identity
    with session_scope() as db:
        other = identity.create_user(db, email="officer2@demo.bank", full_name="Peter Kalyango",
                                     password="WezaDemo!2026", kind="INSTITUTION",
                                     institution_id=uuid.UUID(demo_bank["id"]), roles=["OFFICER"])
        other_id = other.id

    h = as_user("officer2@demo.bank")
    # They cannot see it, and they cannot change it
    assert client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).status_code == 404
    r = client.post(f"/api/v1/inst/opportunities/{oid}/status", headers=_k(h), json={"state": "CONTACTED"})
    assert r.status_code in (403, 404, 422), r.text
    r = client.post(f"/api/v1/inst/opportunities/{oid}/note", headers=h, json={"note": "Not mine."})
    assert r.status_code in (403, 404, 422), r.text

    with session_scope() as db:
        assert db.get(Opportunity, oid).state in ("ROUTED", "ASSIGNED")
        assert db.get(Assignment, oid).user_id != other_id


def test_a_status_cannot_go_backwards(client, as_user, journey, drain, demo_bank):
    """The officer's statuses move forward. A stale click cannot walk an opportunity back to an earlier stage."""
    _j, reference = _routed_to_demo_bank(journey, "0772400104", "I need UGX 15 million for pharmacy stock")
    drain()
    oid = _opp(reference)
    h = as_user(OFFICER)
    assert client.post(f"/api/v1/inst/opportunities/{oid}/status", headers=_k(h), json={"state": "CONTACTED"}).status_code == 200
    back = client.post(f"/api/v1/inst/opportunities/{oid}/status", headers=_k(h), json={"state": "ASSIGNED"})
    assert back.status_code == 409, back.text
    with session_scope() as db:
        assert db.get(Opportunity, oid).state == "CONTACTED"


def test_the_customer_never_sees_an_internal_note(client, as_user, journey, drain, demo_bank):
    """An internal note is the institution's own record: it is audited, and it never reaches the customer."""
    j, reference = _routed_to_demo_bank(journey, "0772400105", "I need UGX 12 million for pharmacy stock")
    drain()
    oid = _opp(reference)
    h = as_user(OFFICER)
    client.post(f"/api/v1/inst/opportunities/{oid}/note", headers=h,
                json={"note": "Internal: the customer asked for a repayment holiday."})

    needs = client.get("/api/v1/me/needs", headers=j.customer_headers).json()["needs"]
    assert "repayment holiday" not in str(needs)
    with session_scope() as db:
        acts = db.execute(select(Activity).where(Activity.opportunity_id == oid,
                                                  Activity.kind == "NOTE")).scalars().all()
        assert len(acts) == 1 and acts[0].note.startswith("Internal:")
