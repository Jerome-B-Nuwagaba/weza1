"""A brand-new institution joins, is verified, configures itself and goes live; a customer then completes a journey
entirely over the WhatsApp webhook and the institution receives the consented opportunity (BRD §6/§10/§22, FSD §53).
Real services end to end; only the outbound HTTP client is mocked and every credential is fake."""

import re
import uuid

from sqlalchemy import select

from tests.helpers import login
from tests.test_whatsapp_channel import (  # noqa: F401 — fixtures are picked up by name
    fake_phone,
    http,
    in_messages,
    journeys_for,
    out_messages,
    send,
    text_msg,
    verified_journey,
    wa_inbound,
)
from weza.domains.opportunity.models import Opportunity
from weza.platform.db import session_scope
from weza.platform.events import drain

PW = "Str0ng-Passw0rd!"
# name, NIN (skipped), the licences (none to send), then the business questions
PROFILE = ["Grace Nakato", "skip", "skip", "Nakato Traders", "Kampala", "3 years", "12 million", "yes", "0", "12 months"]


def _onboard(client, as_user, suffix: str) -> dict:
    name = f"E2E Lender {suffix}"
    r = client.post("/api/v1/institutions/applications", json={
        "legal_name": f"{name} Ltd", "display_name": name, "institution_type": "Tier 4 Microfinance",
        "licence_no": f"T-{suffix}", "regulator": "Other", "representative": {"name": "Rep", "email": f"rep@e{suffix}.co.ug"},
        "compliance": {"name": "Comp", "email": f"comp@e{suffix}.co.ug"}, "admin_name": "Admin",
        "admin_email": f"admin@e{suffix}.co.ug", "admin_password": PW, "accept_terms": True})
    assert r.status_code == 201, r.text
    inst_id = r.json()["institution_id"]
    admin = login(client, f"admin@e{suffix}.co.ug", PW)
    assert client.post(f"/api/v1/admin/institutions/{inst_id}/verify", json={"approve": True, "reason": "Licence checked"},
                       headers=as_user("ops@weza.demo")).status_code == 200
    team = client.post("/api/v1/inst/teams", json={"name": "SME"}, headers=admin).json()
    for local, roles in [("biz", ["BUSINESS", "CREDIT_RISK"]), ("off", ["OFFICER"]), ("mgr", ["MANAGER"])]:
        r = client.post("/api/v1/inst/users", json={"full_name": local, "email": f"{local}@e{suffix}.co.ug", "roles": roles,
                                                    "team_id": team["id"], "password": PW}, headers=admin)
        assert r.status_code == 201, r.text
    biz = login(client, f"biz@e{suffix}.co.ug", PW)
    pid = client.post("/api/v1/inst/products", json={
        "name": f"{name} Duka Loan", "family": "SME_WORKING_CAPITAL",
        "terms": {"min_amount": 1_000_000, "max_amount": 50_000_000, "min_tenor_months": 3, "max_tenor_months": 24},
        "rules": [{"field": "business_age_months", "op": "gte", "value": 6}]}, headers=biz).json()["product_id"]
    client.post(f"/api/v1/inst/products/{pid}/submit", headers=biz)
    assert client.post(f"/api/v1/inst/products/{pid}/review", json={"approve": True, "note": "ok"},
                       headers=admin).status_code == 200
    aid = client.post("/api/v1/inst/appetites", json={
        "name": "Retail traders", "product_ids": [pid], "min_match_score": 40,
        "criteria": [{"field": "amount", "op": "between", "value": [2_000_000, 50_000_000]}]}, headers=biz).json()["appetite_id"]
    client.post(f"/api/v1/inst/appetites/{aid}/simulate", headers=biz)
    assert client.post(f"/api/v1/inst/appetites/{aid}/review", json={"approve": True, "note": "ok"},
                       headers=admin).status_code == 200
    client.put("/api/v1/inst/routing", json={"rules": [{"name": "All", "conditions": {}, "target_team_id": team["id"]}]},
               headers=admin)
    prefs = client.get("/api/v1/inst/notification-prefs", headers=admin).json()["prefs"]
    client.put("/api/v1/inst/notification-prefs", json={"prefs": prefs}, headers=admin)
    assert client.post("/api/v1/inst/activate", headers=admin).json()["status"] == "ACTIVE"
    return {"name": name, "id": inst_id, "admin": admin, "off": login(client, f"off@e{suffix}.co.ug", PW),
            "mgr": login(client, f"mgr@e{suffix}.co.ug", PW)}


def _bot(phone) -> list:
    return [m for m in out_messages(phone) if m.channel == "whatsapp"]


def test_new_institution_receives_a_whatsapp_customers_opportunity(client, as_user, wa_inbound):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    inst = _onboard(client, as_user, suffix)

    # --- customer, entirely over the WhatsApp webhook (signed payloads); the chat number is verified by the channel
    phone = fake_phone()
    verified_journey(client, phone)
    for answer in PROFILE:
        text_msg(client, phone, answer)
        if journeys_for(phone)[0][1] not in ("ASK_PROFILE", "REQUEST_BUSINESS_DOCS"):
            break
    assert journeys_for(phone)[0][1] == "PRESENT_OPTIONS"
    options = next(m.body for m in reversed(_bot(phone)) if f"E2E Lender {suffix}" in m.body)
    number = re.search(r"\*(\d+)\. " + re.escape(inst["name"]), options).group(1)
    text_msg(client, phone, number)
    assert journeys_for(phone)[0][1] == "CONSENT"
    consent = next(m for m in reversed(_bot(phone)) if (m.payload or {}).get("quick_replies"))
    agree = next(q for q in consent.payload["quick_replies"] if q["action"] == "agree")
    send(client, __import__("scripts.replay_whatsapp_webhook", fromlist=["x"]).build(
        "button", phone=phone, button_id=f"agree:{agree['value']}"))
    drain()
    # the number that receives the money: proven by an SMS code typed back into the chat
    assert journeys_for(phone)[0][1] == "PAYOUT_NUMBER"
    send(client, __import__("scripts.replay_whatsapp_webhook", fromlist=["x"]).build(
        "button", phone=phone, button_id="payout_this"))
    # it is the chat number, so the code arrives in the chat itself (any other number would get an SMS)
    sent = next(m.body for m in reversed(out_messages(phone)) if (m.payload or {}).get("kind") == "otp")
    code = re.search(r"\b(\d{6})\b", sent).group(1)
    text_msg(client, phone, code)
    assert journeys_for(phone)[0][1] == "TRACKING"
    assert "OPP-" in " ".join(m.body for m in _bot(phone))  # the customer is told the reference

    # --- the institution sees it, assigned by its own routing rule, with the consented identity
    feed = client.get("/api/v1/inst/opportunities", headers=inst["mgr"]).json()
    rows = feed["items"]
    assert len(rows) == 1 and rows[0]["match_score"] >= 40 and rows[0]["product"].startswith(inst["name"])
    opp_id = rows[0]["id"]
    detail = client.get(f"/api/v1/inst/opportunities/{opp_id}", headers=inst["mgr"]).json()
    assert detail["customer"]["fields"]["full_name"] == "Grace Nakato"
    assert detail["customer"]["fields"]["phone"].endswith(phone[-9:])
    assert detail["customer"]["fields"]["contact_channel"] == "whatsapp"  # reach them where they are
    assert detail["customer"]["fields"]["payout_phone"].endswith(phone[-9:])
    assert detail["consent"]["status"] == "GRANTED"
    assert detail["state"] in ("ASSIGNED", "ROUTED", "RECEIVED")

    # --- the assigned officer can work it; another tenant cannot even see it exists
    assert client.get(f"/api/v1/inst/opportunities/{opp_id}", headers=inst["off"]).status_code == 200
    other = as_user("manager@lakeside.demo")
    assert client.get(f"/api/v1/inst/opportunities/{opp_id}", headers=other).status_code == 404
    with session_scope() as db:
        assert db.execute(select(Opportunity).where(Opportunity.id == uuid.UUID(opp_id))).scalar_one().institution_id


def test_whatsapp_customers_get_self_contained_notifications_without_web_links(client, as_user, wa_inbound):  # noqa: F811
    """After consent the customer is notified of institution outcomes inside WhatsApp: no web link (they have no web
    session) and an invitation to reply in the chat."""
    from weza.domains.customer.models import Customer
    from weza.domains.notification import service as notify
    suffix = uuid.uuid4().hex[:6]
    _onboard(client, as_user, suffix)
    phone = fake_phone()
    verified_journey(client, phone)
    with session_scope() as db:
        from weza.platform.models import GraphInstance
        gi = db.get(GraphInstance, journeys_for(phone)[0][0])
        cust = db.get(Customer, uuid.UUID(gi.state["customer_id"]))
        notify.notify_customer(db, cust.id, "OutcomeReported", title="Update", body="Acacia reported your request approved.",
                               link="/c/status", channel="whatsapp")
    last = [m for m in out_messages(phone) if m.channel == "whatsapp"][-1].body
    assert "Reply here any time" in last and "/c/status" not in last and "http" not in last
