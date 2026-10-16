"""Institution â†’ customer information requests: gated by the Disclosure Gateway and consent scope, relayed to the
customer, answered by choice, and closed when consent or the opportunity ends."""

import uuid

from sqlalchemy import select

from tests.helpers import SME_ANSWERS
from weza.domains.identity.models import User
from weza.domains.opportunity.models import Assignment, Opportunity
from weza.platform.db import session_scope
from weza.platform.events import drain

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _k(headers: dict) -> dict:
    return {**headers, "Idempotency-Key": uuid.uuid4().hex}


def _routed(journey, phone: str):
    j = journey("I need UGX 20 million to buy stock for my pharmacy")
    j.send(action="confirm")
    j.verify(phone)
    j.answer_profile({**SME_ANSWERS, "identity.nin": f"CM{phone}AB"})
    opt = next(o for o in j.cards("options")[0]["options"] if o["institution"] == "Lakeside Bank")
    j.send(action="select", value=opt["match_id"])
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    ref = j.cards("submitted")[0]["reference"]
    drain()
    with session_scope() as db:
        o = db.execute(select(Opportunity).where(Opportunity.reference == ref)).scalar_one()
        owner = db.get(User, db.get(Assignment, o.id).user_id).email
        return j, str(o.id), owner


def test_officer_requests_document_customer_answers(client, as_user, journey):
    j, oid, owner = _routed(journey, "0772400001")
    h = as_user(owner)
    view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
    assert view["can_request_info"] and view["can_request_documents"] and view["info_requests"] == []

    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=_k(h), json={
        "kind": "DOCUMENT", "doc_type": "bank_statement", "message": "Please share 6 months of statements."})
    assert r.status_code == 201, r.text
    req = r.json()["info_requests"][0]
    assert req["status"] == "OPEN" and req["doc_label"].startswith("Bank statement")
    drain()

    mine = client.get("/api/v1/me/info-requests", headers=j.customer_headers).json()
    assert mine["open"] == 1 and mine["requests"][0]["institution"] == "Lakeside Bank"
    notes = client.get("/api/v1/me/notifications", headers=j.customer_headers).json()["notifications"]
    assert any("asked for a document" in n["title"] for n in notes)

    # A question can't be answered with nothing; a document request needs a stored document
    bad = client.post(f"/api/v1/me/info-requests/{req['id']}/respond", headers=j.customer_headers, json={})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "DOCUMENT_REQUIRED"
    doc = client.post("/api/v1/me/documents", headers=j.customer_headers, data={"doc_type": "bank_statement"},
                      files={"file": ("statement.pdf", PDF, "application/pdf")}).json()
    ok = client.post(f"/api/v1/me/info-requests/{req['id']}/respond", headers=j.customer_headers,
                     json={"document_id": doc["id"]})
    assert ok.status_code == 200 and ok.json()["open"] == 0
    drain()

    after = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
    assert after["info_requests"][0]["status"] == "FULFILLED"
    assert after["info_requests"][0]["document_id"] == doc["id"]
    assert client.get(f"/api/v1/inst/opportunities/{oid}/documents/{doc['id']}", headers=h).status_code == 200
    assert any(a["kind"] == "INFO_PROVIDED" for a in after["activity"])


def test_request_gating(client, as_user, journey):
    j, oid, owner = _routed(journey, "0772400002")
    # Unassigned officer and executives can't ask: they can't see the customer
    other = next(e for e in ("officer@lakeside.demo", "officer2@lakeside.demo", "asset@lakeside.demo") if e != owner)
    for email in (other, "exec@lakeside.demo"):
        r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=_k(as_user(email)),
                        json={"kind": "QUESTION", "message": "How many staff do you have?"})
        assert r.status_code in (403, 422), r.text
    # Other tenants get 404
    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=_k(as_user("manager@pearl.demo")),
                    json={"kind": "QUESTION", "message": "Hi"})
    assert r.status_code in (403, 404)
    # Scam-shaped asks are refused
    h = as_user(owner)
    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=_k(h),
                    json={"kind": "QUESTION", "message": "Please send us your mobile money PIN"})
    assert r.json()["error"]["code"] == "FORBIDDEN_ASK"


def test_consent_withdrawal_closes_open_requests(client, as_user, journey):
    j, oid, owner = _routed(journey, "0772400003")
    h = as_user(owner)
    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=_k(h),
                    json={"kind": "QUESTION", "message": "How many staff do you employ?"})
    req_id = r.json()["info_requests"][0]["id"]
    consents = client.get("/api/v1/me/consents", headers=j.customer_headers).json()["consents"]
    client.post(f"/api/v1/me/consents/{consents[0]['id']}/withdraw", headers=j.customer_headers)
    drain()
    mine = client.get("/api/v1/me/info-requests", headers=j.customer_headers).json()
    assert mine["open"] == 0 and mine["requests"][0]["status"] == "CANCELLED"
    r = client.post(f"/api/v1/me/info-requests/{req_id}/respond", headers=j.customer_headers,
                    json={"response_text": "Six"})
    assert r.status_code == 422
    view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
    assert view["can_request_info"] is False and "response_text" not in view["info_requests"][0]
