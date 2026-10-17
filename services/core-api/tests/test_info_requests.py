"""Institution → customer information requests: gated by the Disclosure Gateway and consent scope, relayed to the
customer, answered by choice, and closed when consent or the opportunity ends."""

from tests.helpers import idem as _k
from tests.helpers import routed_to_lakeside as _routed
from weza.platform.events import drain

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


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


def _ask(client, h, oid, **body):
    return client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=_k(h), json=body)


def test_privacy_violation_is_403(client, as_user, journey):
    """Spec §2B: asking without a disclosure PERMIT is a privacy violation, not a validation error."""
    j, oid, owner = _routed(journey, "0772400011")
    other = next(e for e in ("officer@lakeside.demo", "officer2@lakeside.demo", "asset@lakeside.demo") if e != owner)
    r = _ask(client, as_user(other), oid, kind="QUESTION", message="How many staff do you have?")
    assert r.status_code == 403 and r.json()["error"]["code"] == "PRIVACY_VIOLATION"


def test_expiry_sweep_closes_overdue_requests_and_tells_both_sides(client, as_user, journey):
    from datetime import timedelta

    from weza.domains.opportunity import service as opp_svc
    from weza.domains.opportunity.models import InfoRequest
    from weza.platform.db import session_scope, utcnow
    j, oid, owner = _routed(journey, "0772400012")
    h = as_user(owner)
    req_id = _ask(client, h, oid, kind="QUESTION", message="When did you start trading?").json()["info_requests"][0]["id"]
    assert client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()["awaiting_customer"] is True
    with session_scope() as db:
        db.get(InfoRequest, req_id).due_at = utcnow() - timedelta(minutes=1)
    with session_scope() as db:
        assert opp_svc.info_request_expiry_sweep(db) >= 1
    drain()
    view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
    assert view["info_requests"][0]["status"] == "EXPIRED" and view["awaiting_customer"] is False
    assert any(a["kind"] == "INFO_REQUEST_EXPIRED" for a in view["activity"])
    notes = client.get("/api/v1/me/notifications", headers=j.customer_headers).json()["notifications"]
    assert any(n["title"] == "A request has expired" for n in notes)
    # An expired request can't be answered
    r = client.post(f"/api/v1/me/info-requests/{req_id}/fulfil", headers=j.customer_headers,
                    json={"response_text": "2019"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_OPEN"


def test_spec_route_aliases_and_waiting_flag_in_feed(client, as_user, journey):
    j, oid, owner = _routed(journey, "0772400013")
    h = as_user(owner)
    req_id = _ask(client, h, oid, kind="QUESTION", message="Who are your main suppliers?").json()["info_requests"][0]["id"]
    mine =client.get("/api/v1/inst/my-day", headers=h).json()["sections"]
    item = next(i for s in mine.values() for i in s if i["id"] == oid)
    assert item["awaiting_customer"] and item["next_action"] == "Waiting for customer info"
    r = client.delete(f"/api/v1/inst/opportunities/{oid}/info-requests/{req_id}", headers=h,
                      params={"reason": "Asked by phone instead"})
    assert r.status_code == 200 and r.json()["info_requests"][0]["status"] == "CANCELLED"
    assert r.json()["info_requests"][0]["cancel_reason"] == "Asked by phone instead"


def test_answer_saved_to_profile_with_provenance_and_market_recleared(client, as_user, journey):
    """Spec §5: an answer tied to a profile field becomes a SELF_REPORTED fact sourced to the request, and the
    customer's open demand is re-cleared."""
    from sqlalchemy import select

    from weza.domains.customer.service import current_facts
    from weza.domains.matching.models import ClearingRun
    from weza.domains.opportunity.models import InfoRequest
    from weza.platform.db import session_scope
    phone = "0772400014"
    j, oid, owner = _routed(journey, phone)
    h = as_user(owner)
    bad = _ask(client, h, oid, kind="QUESTION", message="Turnover?", fact_key="identity.nin")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "FACT_KEY_INVALID"
    req_id = _ask(client, h, oid, kind="QUESTION", message="What is your current monthly turnover?",
                  fact_key="business.monthly_turnover").json()["info_requests"][0]["id"]
    # The same customer has another request still at the options stage (active demand)
    j2 = journey("I need UGX 8 million for a delivery motorcycle")
    j2.send(action="confirm")
    j2.verify(phone)
    j2.answer_profile({"need.tenor_months": "12 months"})
    r = client.post(f"/api/v1/me/info-requests/{req_id}/fulfil", headers=j.customer_headers,
                    json={"response_text": "not sure"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ANSWER_INVALID"
    r = client.post(f"/api/v1/me/info-requests/{req_id}/fulfil", headers=j.customer_headers,
                    json={"response_text": "15 million"})
    assert r.status_code == 200, r.text
    drain()
    with session_scope() as db:
        cid = db.get(InfoRequest, req_id).customer_id
        fact = current_facts(db, cid)["business.monthly_turnover"]
        assert fact.value["v"] == 15_000_000 and fact.verification_state == "SELF_REPORTED"
        assert fact.source == "CUSTOMER" and fact.source_channel == "info_request"
        assert fact.source_ref == f"info_request:{req_id}"
        runs = db.execute(select(ClearingRun).where(ClearingRun.trigger_event == "InfoRequestFulfilled",
                                                    ClearingRun.trigger_ref == req_id)).scalars().all()
        assert runs


def test_requests_stay_within_the_consented_categories(client, as_user, journey):
    """Consent scope (trust/policy.py): without DOCUMENTS consent no document can be requested; without FINANCIAL consent
    no financial profile field can be asked for — and the form only offers fields the customer agreed to share."""
    import uuid

    from weza.domains.consent.models import Consent
    from weza.domains.opportunity.models import Opportunity
    from weza.platform.db import session_scope
    j, oid, owner = _routed(journey, "0772400015")
    with session_scope() as db:
        c = db.get(Consent, db.get(Opportunity, uuid.UUID(oid)).consent_id)
        c.data_categories = ["CONTACT", "PROFILE"]
    h = as_user(owner)
    for body in ({"kind": "DOCUMENT", "doc_type": "bank_statement", "message": "Six months of statements please."},
                 {"kind": "QUESTION", "message": "What is your monthly turnover?", "fact_key": "business.monthly_turnover"}):
        r = _ask(client, h, oid, **body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "PRIVACY_VIOLATION", r.text
    r = _ask(client, h, oid, kind="QUESTION", message="How long has the business traded?", fact_key="business.age_months")
    assert r.status_code == 201, r.text
    view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
    assert "business.age_months" in view["fact_fields"] and "business.monthly_turnover" not in view["fact_fields"]
    assert view["can_request_documents"] is False


def test_infected_upload_never_reaches_the_institution(client, as_user, journey):
    """Quarantine pipeline: a file that fails the malware scan is REJECTED, its bytes are discarded, and it can't be
    used to answer a request or be downloaded by the institution."""
    from weza.domains.customer.documents import EICAR
    from weza.domains.customer.models import DocumentBlob
    from weza.platform.db import session_scope
    j, oid, owner = _routed(journey, "0772400016")
    h = as_user(owner)
    req = _ask(client, h, oid, kind="DOCUMENT", doc_type="bank_statement",
               message="Please share your statements.").json()["info_requests"][0]
    doc = client.post("/api/v1/me/documents", headers=j.customer_headers, data={"doc_type": "bank_statement"},
                      files={"file": ("statement.pdf", b"%PDF-1.4\n" + EICAR, "application/pdf")}).json()
    assert doc["state"] == "REJECTED"
    with session_scope() as db:
        assert db.get(DocumentBlob, doc["id"]) is None
    r = client.post(f"/api/v1/me/info-requests/{req['id']}/respond", headers=j.customer_headers,
                    json={"document_id": doc["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "DOCUMENT_NOT_READY"
    assert client.get(f"/api/v1/inst/opportunities/{oid}/documents/{doc['id']}", headers=h).status_code == 404
    view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
    assert doc["id"] not in {d["id"] for d in view["customer"].get("documents", [])}
