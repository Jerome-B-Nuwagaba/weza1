"""Institution onboarding graph: apply → verify → users → product (maker-checker) → appetite (simulate, approve)
→ routing → notifications → activate (AT-22…AT-28)."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from tests.helpers import idem, login, opp_for, routed_to_lakeside
from weza.domains.appetite import service as appetite_svc
from weza.domains.appetite.models import Appetite, AppetiteVersion
from weza.domains.commercial.models import CommercialEvent
from weza.domains.institution.models import Institution
from weza.domains.intelligence import insights
from weza.domains.matching import engine
from weza.domains.matching.rules import ruleset_hash
from weza.domains.opportunity.models import Insight, Opportunity, Preview
from weza.domains.opportunity.service import DECLINE_REASONS
from weza.domains.product.models import Product, ProductVersion
from weza.domains.trust.models import AuditEvent
from weza.platform.db import session_scope, utcnow

PW = "Str0ng-Passw0rd!"


def test_full_onboarding_to_activation(client, as_user):
    suffix = uuid.uuid4().hex[:6]
    r = client.post("/api/v1/institutions/applications", json={
        "legal_name": f"Test Lender {suffix} Ltd", "institution_type": "Fintech Lender", "licence_no": "T-1",
        "regulator": "Other", "representative": {"name": "Rep One", "email": f"rep@t{suffix}.co.ug"},
        "compliance": {"name": "Comp One", "email": f"comp@t{suffix}.co.ug"}, "admin_name": "Admin One",
        "admin_email": f"admin@t{suffix}.co.ug", "admin_password": PW, "accept_terms": True})
    assert r.status_code == 201, r.text
    inst_id = r.json()["institution_id"]
    admin = login(client, f"admin@t{suffix}.co.ug", PW)

    ws = client.get("/api/v1/inst/workspace", headers=admin).json()
    assert ws["institution"]["status"] == "SUBMITTED" and not ws["onboarding"]["ready"]
    assert client.post("/api/v1/inst/activate", headers=admin).status_code == 422  # not verified

    # WEZA Ops verifies (human node)
    ops = as_user("ops@weza.demo")
    assert client.post(f"/api/v1/admin/institutions/{inst_id}/verify", json={"approve": True, "reason": "Licence ok"},
                       headers=ops).status_code == 200

    # Users & team
    team = client.post("/api/v1/inst/teams", json={"name": "Core"}, headers=admin).json()
    for email, roles in [(f"biz@t{suffix}.co.ug", ["BUSINESS", "CREDIT_RISK"]), (f"off@t{suffix}.co.ug", ["OFFICER"]),
                         (f"mgr@t{suffix}.co.ug", ["MANAGER"])]:
        r = client.post("/api/v1/inst/users", json={"full_name": email.split("@")[0], "email": email, "roles": roles,
                                                    "team_id": team["id"], "password": PW}, headers=admin)
        assert r.status_code == 201, r.text
    biz = login(client, f"biz@t{suffix}.co.ug", PW)

    # Product: maker-checker
    prod = client.post("/api/v1/inst/products", json={
        "name": "Test Loan", "family": "SME_WORKING_CAPITAL",
        "terms": {"min_amount": 1_000_000, "max_amount": 50_000_000, "min_tenor_months": 3, "max_tenor_months": 24},
        "rules": [{"field": "customer_type", "op": "in", "value": ["SME"]}]}, headers=biz).json()
    pid = prod["product_id"]
    assert client.post(f"/api/v1/inst/products/{pid}/submit", headers=biz).status_code == 200
    r = client.post(f"/api/v1/inst/products/{pid}/review", json={"approve": True}, headers=biz)
    assert r.status_code == 422 and r.json()["error"]["code"] == "MAKER_CHECKER"
    r = client.post(f"/api/v1/inst/products/{pid}/review", json={"approve": True, "note": "ok"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"

    # Appetite: simulation required before approval
    ap = client.post("/api/v1/inst/appetites", json={"name": "Test mandate", "product_ids": [pid],
                                                     "criteria": [{"field": "region", "op": "in", "value": ["Central"]}],
                                                     "min_match_score": 60}, headers=biz).json()
    aid = ap["appetite_id"]
    r = client.post(f"/api/v1/inst/appetites/{aid}/review", json={"approve": True}, headers=admin)
    assert r.json()["error"]["code"] == "SIMULATION_REQUIRED"
    sim = client.post(f"/api/v1/inst/appetites/{aid}/simulate", headers=biz).json()
    assert sim["demand_considered"] > 0 and "inside" in sim and "near_miss_reasons" in sim
    for cell in list(sim["by_region"].values()):
        assert cell >= 5  # k-anonymity (TSD §39)
    assert client.post(f"/api/v1/inst/appetites/{aid}/review", json={"approve": True, "note": "ok"},
                       headers=admin).status_code == 200

    # Routing & notifications, then activation
    checklist = client.get("/api/v1/inst/workspace", headers=admin).json()["onboarding"]
    assert {i["key"] for i in checklist["items"] if not i["done"]} == {"routing", "notifications"}
    client.put("/api/v1/inst/routing", json={"rules": [{"name": "All", "conditions": {}, "target_team_id": team["id"]}]},
               headers=admin)
    prefs = client.get("/api/v1/inst/notification-prefs", headers=admin).json()["prefs"]
    client.put("/api/v1/inst/notification-prefs", json={"prefs": prefs}, headers=admin)
    r = client.post("/api/v1/inst/activate", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE", r.text
    aps = client.get("/api/v1/inst/appetites", headers=admin).json()["appetites"]
    assert aps[0]["lifecycle_status"] == "ACTIVE"


def test_ai_extraction_is_only_a_proposal_until_people_approve_it(client, as_user):
    """FSD §18 / HUMAN_PRODUCT_DECISION: AI extraction saves nothing; an AI-sourced product starts as DRAFT, matches no
    one, and its author can't approve it."""
    credit = as_user("credit@lakeside.demo")
    policy_text = (b"SME Working Capital Loan. Minimum amount UGX 2,000,000; maximum UGX 40,000,000. Tenor 3 to 18 "
                   b"months. Applicants must be registered businesses trading for at least 2 years in Central region.")
    with session_scope() as db:
        before = db.execute(select(func.count()).select_from(Product)).scalar_one()
    r = client.post("/api/v1/inst/products/extract", headers=credit,
                    files={"file": ("policy.txt", policy_text, "text/plain")})
    assert r.status_code == 200, r.text
    assert "proposal" in r.json() and "Nothing is active" in r.json()["notice"]
    with session_scope() as db:
        assert db.execute(select(func.count()).select_from(Product)).scalar_one() == before

    r = client.post("/api/v1/inst/products", headers=credit, json={
        "name": f"AI drafted loan {uuid.uuid4().hex[:4]}", "family": "SME_WORKING_CAPITAL",
        "terms": {"min_amount": 2_000_000, "max_amount": 40_000_000, "min_tenor_months": 3, "max_tenor_months": 18},
        "provenance": {"source": r.json()["proposal"].get("source"), "filename": "policy.txt"}})
    assert r.status_code == 201, r.text
    pid = r.json()["product_id"]
    assert r.json()["version"]["status"] == "DRAFT" and r.json()["version"]["provenance"]
    with session_scope() as db:
        assert db.get(Product, uuid.UUID(pid)).status == "DRAFT"
        assert all(s.product.id != uuid.UUID(pid) for s in engine.active_supply(db))
    client.post(f"/api/v1/inst/products/{pid}/submit", headers=credit)
    r = client.post(f"/api/v1/inst/products/{pid}/review", headers=credit, json={"approve": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MAKER_CHECKER"


def test_mandate_expires_when_its_campaign_ends(client, as_user):
    """Mandate lifecycle: an ACTIVE appetite whose campaign has ended becomes EXPIRED (terminal) and is audited."""
    credit, admin = as_user("credit@lakeside.demo"), as_user("admin@lakeside.demo")
    own = client.get("/api/v1/inst/products", headers=credit).json()["products"][0]["id"]
    aid = client.post("/api/v1/inst/appetites", headers=credit, json={
        "name": "Short campaign", "product_ids": [own], "criteria": [{"field": "region", "op": "in", "value": ["Central"]}],
        "campaign_from": (date.today() - timedelta(days=30)).isoformat(),
        "campaign_to": (date.today() + timedelta(days=30)).isoformat()}).json()["appetite_id"]
    assert client.post(f"/api/v1/inst/appetites/{aid}/simulate", headers=credit).status_code == 200
    r = client.post(f"/api/v1/inst/appetites/{aid}/review", headers=admin, json={"approve": True, "note": "ok"})
    assert r.status_code == 200 and r.json()["lifecycle_status"] == "ACTIVE", r.text

    with session_scope() as db:
        ap = db.get(Appetite, uuid.UUID(aid))
        db.get(AppetiteVersion, ap.active_version_id).campaign_to = date.today() - timedelta(days=1)
    with session_scope() as db:
        assert appetite_svc.expiry_sweep(db) >= 1
    detail = client.get(f"/api/v1/inst/appetites/{aid}", headers=credit).json()
    assert detail["lifecycle_status"] == "EXPIRED"
    r = client.post(f"/api/v1/inst/appetites/{aid}/status", headers=admin, json={"status": "ACTIVE", "reason": "again"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TRANSITION"
    with session_scope() as db:
        assert db.execute(select(AuditEvent).where(AuditEvent.action == "appetite.expired",
                                                   AuditEvent.object_id == aid)).first()


def test_outcome_learning_loop_recommends_but_never_changes_lender_rules(client, as_user):
    """BR-004: decline patterns produce an insight for people to act on; neither the nightly job nor actioning the
    insight alters any product or appetite rule."""
    def rules():
        with session_scope() as db:
            return ({(str(v.id), v.status, ruleset_hash(v.rules), str(v.terms)) for v in
                     db.execute(select(ProductVersion)).scalars()},
                    {(str(v.id), v.status, str(v.criteria), v.min_match_score) for v in
                     db.execute(select(AppetiteVersion)).scalars()},
                    {(str(a.id), a.lifecycle_status, str(a.active_version_id)) for a in db.execute(select(Appetite)).scalars()})
    before = rules()
    with session_scope() as db:
        insights.outcome_insights_job(db)
    credit = as_user("credit@lakeside.demo")
    ins = next(i for i in client.get("/api/v1/inst/intelligence/insights", headers=credit).json()["insights"]
               if i["kind"] == "APPETITE_OUTCOME_MISMATCH")
    assert "will not change your appetite automatically" in ins["narrative"]
    r = client.post(f"/api/v1/inst/intelligence/insights/{ins['id']}", headers=credit,
                    json={"status": "ACTIONED", "note": "Reviewing turnover threshold with credit committee"})
    assert r.status_code == 200
    assert rules() == before


def test_consequential_workspace_actions_leave_complete_audit_rows(client, as_user, journey):
    """TSD §53: viewing Level-3 details, assigning, requesting info, updating status, reporting an outcome and changing
    a mandate's lifecycle/capacity each write an audit row with actor, tenant, action, before/after state, IP and time."""
    _, oid, owner = routed_to_lakeside(journey, "0772470003")
    manager, officer = as_user("manager@lakeside.demo"), as_user(owner)
    credit, admin = as_user("credit@lakeside.demo"), as_user("admin@lakeside.demo")
    with session_scope() as db:
        lakeside = db.execute(select(Institution).where(Institution.display_name == "Lakeside Bank")).scalar_one().id
        start = db.execute(select(func.max(AuditEvent.at))).scalar_one()
    assert client.get(f"/api/v1/inst/opportunities/{oid}", headers=officer).json()["customer"]["restricted"] is False
    owner_id = client.get(f"/api/v1/inst/opportunities/{oid}", headers=manager).json()["owner_id"]
    assert client.post(f"/api/v1/inst/opportunities/{oid}/assign", headers=manager,
                       json={"user_id": owner_id, "reason": "Re-confirming owner"}).status_code == 200
    assert client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=idem(officer),
                       json={"kind": "QUESTION", "message": "How many staff?"}).status_code == 201
    assert client.post(f"/api/v1/inst/opportunities/{oid}/status", headers=idem(officer),
                       json={"state": "CONTACTED", "note": "Called"}).status_code == 200
    assert client.post(f"/api/v1/inst/opportunities/{oid}/outcome", headers=idem(officer),
                       json={"state": "REPORTED_DECLINED", "reason_category": next(iter(DECLINE_REASONS))}).status_code == 200
    ap = next(a for a in client.get("/api/v1/inst/appetites", headers=credit).json()["appetites"]
              if a["lifecycle_status"] == "ACTIVE")["id"]
    for status in ("PAUSED", "ACTIVE"):
        assert client.post(f"/api/v1/inst/appetites/{ap}/status", headers=admin,
                           json={"status": status, "reason": "audit test"}).status_code == 200
    assert client.post(f"/api/v1/inst/appetites/{ap}/capacity", headers=credit,
                       json={"override": None, "reason": "audit test"}).status_code == 200

    with session_scope() as db:
        rows = db.execute(select(AuditEvent).where(AuditEvent.at > start, AuditEvent.institution_id == lakeside,
                                                   AuditEvent.actor_type == "INSTITUTION_USER")).scalars().all()
        by_action = {(r.action, r.object_id): r for r in rows}
    expected = [("opportunity.viewed", oid, False), ("opportunity.assigned", oid, True),
                ("info_request.created", None, False), ("opportunity.status", oid, True),
                ("appetite.paused", ap, True), ("appetite.active", ap, True), ("appetite.capacity_override", ap, True)]
    for action, obj, needs_before in expected:
        r = next((r for (a, o), r in by_action.items() if a == action and (obj is None or o == obj)), None)
        assert r is not None, f"no audit row for {action}"
        assert r.actor_id and r.institution_id == lakeside and r.ip and r.at and r.after is not None, action
        assert (r.before is not None) or not needs_before, f"{action} has no previous state"
    states = {(r.before or {}).get("state"): r.after.get("state") for r in rows
              if r.action == "opportunity.status" and r.object_id == oid}
    assert states.get("CONTACTED") == "REPORTED_DECLINED"  # the outcome itself is audited with before/after


def test_sandbox_uses_synthetic_customers_only(client, as_user):
    """AT-53 / TSD §74."""
    r = client.post("/api/v1/inst/sandbox/runs", headers=as_user("business@lakeside.demo"))
    body = r.json()
    assert r.status_code == 200 and body["synthetic"] is True and body["results"]
    assert all(x["synthetic_id"].startswith("SYN-") for x in body["results"])


def test_command_centre_is_role_personalised(client, as_user):
    """AT-29 / FSD-CMD-002."""
    mgr = client.get("/api/v1/inst/command-centre", headers=as_user("manager@lakeside.demo")).json()
    off = client.get("/api/v1/inst/command-centre", headers=as_user("officer@lakeside.demo")).json()
    assert mgr["briefing"] and set(mgr["cards"]) == set(off["cards"])
    assert sum(mgr["funnel"].values()) >= sum(off["funnel"].values())


def test_command_centre_tiles_and_urgent_cases_are_real_counts(client, as_user):
    """The four Command Centre tiles are counts WEZA holds, and every urgent case carries the columns the
    Urgent cases table shows — without naming the customer."""
    d = client.get("/api/v1/inst/command-centre", headers=as_user("manager@lakeside.demo")).json()
    k = d["kpis"]
    assert k["attention"] >= len(d["attention"]) and k["attention_high"] <= k["attention"]
    assert k["new_24h"] >= len(d["new_opportunities"])
    assert k["new_7d"] >= k["new_24h"]
    assert k["active_products"] == len(d["active_products"]) <= k["products_total"]
    assert k["active_mandates"] == len(d["active_mandates"]) <= k["mandates_total"]
    for case in (c for c in d["attention"] if c.get("id")):
        assert {"customer", "product", "issue", "owner", "updated_at", "severity", "reference"} <= set(case)
        assert "@" not in case["customer"]
    assert len(d["priority"]) <= 5
    assert all(p["match_status"] in ("HIGH", "GOOD", "UNDER_REVIEW") for p in d["priority"])


def test_priority_opportunities_never_name_a_customer_to_a_role_without_identity_access(client, as_user):
    """An executive may see the best matches, but the Disclosure Gateway withholds the business name."""
    d = client.get("/api/v1/inst/command-centre", headers=as_user("exec@lakeside.demo")).json()
    assert all(p["business_name"] is None and p["description"] for p in d["priority"])


def test_assistant_answers_from_tools_read_only(client, as_user):
    """AT-38: deterministic assistant routes to permitted tools and never mutates."""
    r = client.post("/api/v1/inst/ask", json={"question": "Show my best SME opportunities today"},
                    headers=as_user("manager@lakeside.demo")).json()
    assert r["tool_calls"][0]["tool"] == "search_opportunities" and r["answer"]
    r = client.post("/api/v1/inst/ask", json={"question": "What sits just outside our appetite?"},
                    headers=as_user("credit@lakeside.demo")).json()
    assert r["tool_calls"][0]["tool"] == "get_near_match_analysis"


def test_assistant_explains_a_match_and_reports_product_status(client, as_user):
    """The Command Centre suggestions: why an opportunity matched, and which products are live — both read-only
    and scoped to the asker's institution."""
    h = as_user("manager@lakeside.demo")
    r = client.post("/api/v1/inst/ask", json={"question": "Explain why this SME was matched"}, headers=h).json()
    call = r["tool_calls"][0]
    assert call["tool"] == "explain_match" and call["result"]["reference"] and "credit decision" in r["answer"]
    ref = call["result"]["reference"]
    again = client.post("/api/v1/inst/ask", json={"question": f"Why was {ref} matched?"}, headers=h).json()
    assert again["tool_calls"][0]["result"]["reference"] == ref
    # Another institution's user cannot read it by reference.
    other = client.post("/api/v1/inst/ask", json={"question": f"Why was {ref} matched?"},
                        headers=as_user("manager@pearl.demo")).json()
    assert "error" in other["tool_calls"][0]["result"]
    # An officer (no analytics access) can still ask which products are live.
    p = client.post("/api/v1/inst/ask", json={"question": "Is our SME Working Capital product active?"},
                    headers=as_user("officer@lakeside.demo")).json()
    assert p["tool_calls"][0]["tool"] == "get_product_status" and "Your products" in p["answer"]


def test_outcome_insight_exists_and_appetite_unchanged(client, as_user):
    """AT-40 / BR-004: mismatch insight raised; appetite not altered automatically."""
    h = as_user("credit@lakeside.demo")
    ins = client.get("/api/v1/inst/intelligence/insights", headers=h).json()["insights"]
    assert any(i["kind"] == "APPETITE_OUTCOME_MISMATCH" for i in ins)
    aps = client.get("/api/v1/inst/appetites", headers=h).json()["appetites"]
    assert all(a["active_version"] == 1 for a in aps)


# ------------------------------------------------------------------ tenant isolation & RBAC (AT-SEC-01, TSD §47/§48)

OFFICERS = ("officer@lakeside.demo", "officer2@lakeside.demo", "asset@lakeside.demo")


@pytest.fixture()
def pearl():
    """Ids of Pearl SACCO's own records, to prove Lakeside users can neither see nor change them."""
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == "Pearl SACCO")).scalar_one()
        product = db.execute(select(Product).where(Product.institution_id == inst.id).limit(1)).scalar_one()
        appetite = db.execute(select(Appetite).where(Appetite.institution_id == inst.id).limit(1)).scalar_one()
        insight = Insight(institution_id=inst.id, kind="LOW_FILL", dedupe_key=f"test:{uuid.uuid4().hex}",
                          title="Pearl-only insight", narrative="Pearl-only insight")
        preview = Preview(need_id=uuid.uuid4(), match_id=uuid.uuid4(), institution_id=inst.id, payload={},
                          expires_at=utcnow() + timedelta(days=1))
        event = CommercialEvent(idempotency_key=f"test:{uuid.uuid4().hex}", institution_id=inst.id,
                                kind="QUALIFIED_OPPORTUNITY", status="BILLABLE",
                                billing_period=utcnow().strftime("%Y-%m"))
        db.add_all([insight, preview, event])
        db.flush()
        return {"opp": opp_for("Pearl SACCO")[0], "product": str(product.id), "appetite": str(appetite.id),
                "insight": str(insight.id), "preview": str(preview.id), "event": str(event.id)}


def test_another_tenants_records_are_not_found_on_every_route(client, as_user, pearl):
    """Every by-id institution route answers 404 for another tenant's record, so its existence never leaks."""
    manager, credit, admin = (as_user(e) for e in ("manager@lakeside.demo", "credit@lakeside.demo",
                                                    "admin@lakeside.demo"))
    lakeside_user = client.get("/api/v1/inst/users", headers=admin).json()["users"][0]["id"]
    opp, prod, ap = pearl["opp"], pearl["product"], pearl["appetite"]
    product_body = {"name": "Hijacked", "family": "SME_GROWTH", "terms": {"min_amount": 1, "max_amount": 2}}
    attempts = [
        (manager, "get", f"/inst/opportunities/{opp}", None),
        (manager, "post", f"/inst/opportunities/{opp}/status", {"state": "CONTACTED"}),
        (manager, "post", f"/inst/opportunities/{opp}/outcome", {"state": "WITHDRAWN"}),
        (manager, "post", f"/inst/opportunities/{opp}/assign", {"user_id": lakeside_user}),
        (manager, "post", f"/inst/opportunities/{opp}/info-requests", {"kind": "QUESTION", "message": "Hello?"}),
        (manager, "get", f"/inst/opportunities/{opp}/documents/{uuid.uuid4()}", None),
        (credit, "get", f"/inst/products/{prod}", None),
        (credit, "put", f"/inst/products/{prod}", product_body),
        (credit, "post", f"/inst/products/{prod}/submit", None),
        (credit, "post", f"/inst/products/{prod}/review", {"approve": True}),
        (credit, "post", f"/inst/products/{prod}/status", {"status": "PAUSED", "reason": "hijack"}),
        (credit, "get", f"/inst/appetites/{ap}", None),
        (credit, "put", f"/inst/appetites/{ap}", {"name": "Hijacked", "product_ids": [prod]}),
        (credit, "post", f"/inst/appetites/{ap}/simulate", None),
        (credit, "post", f"/inst/appetites/{ap}/review", {"approve": True}),
        (credit, "post", f"/inst/appetites/{ap}/status", {"status": "PAUSED", "reason": "hijack"}),
        (credit, "post", f"/inst/appetites/{ap}/capacity", {"override": "PAUSED", "reason": "hijack"}),
        (credit, "post", f"/inst/intelligence/insights/{pearl['insight']}", {"status": "DISMISSED", "note": "hijack"}),
        (credit, "post", f"/inst/previews/{pearl['preview']}/interest", {"state": "INTERESTED"}),
        (admin, "post", f"/inst/billing/events/{pearl['event']}/dispute",
         {"reason": "DUPLICATE", "description": "Not our opportunity at all."}),
    ]
    for headers, method, path, body in attempts:
        r = client.request(method, f"/api/v1{path}", headers=idem(headers), json=body)
        assert r.status_code == 404, f"{method.upper()} {path} -> {r.status_code} {r.text}"
        assert r.json()["error"]["code"] == "NOT_FOUND"
    # An id taken from the request body is checked too: an appetite can't be built on another tenant's product
    r = client.post("/api/v1/inst/appetites", headers=credit, json={"name": "Borrowed", "product_ids": [prod]})
    assert r.status_code == 422
    with session_scope() as db:  # nothing of Pearl's changed
        assert db.get(Product, uuid.UUID(prod)).name != "Hijacked"
        assert db.get(Insight, uuid.UUID(pearl["insight"])).status == "OPEN"
        assert db.get(Preview, uuid.UUID(pearl["preview"])).interest_state == "PENDING"


def test_officer_acts_only_on_assigned_opportunities(client, as_user, journey):
    """An officer can't see, report an outcome on, or cancel requests of a colleague's opportunity; a manager can."""
    _, oid, owner = routed_to_lakeside(journey, "0772470001")
    colleague = as_user(next(e for e in OFFICERS if e != owner))
    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests", headers=idem(as_user(owner)),
                    json={"kind": "QUESTION", "message": "How long has the pharmacy traded?"})
    assert r.status_code == 201, r.text
    req = r.json()["info_requests"][0]["id"]

    assert client.get(f"/api/v1/inst/opportunities/{oid}", headers=colleague).status_code == 404
    assert oid not in {i["id"] for i in client.get("/api/v1/inst/opportunities", headers=colleague).json()["items"]}
    r = client.post(f"/api/v1/inst/opportunities/{oid}/outcome", headers=idem(colleague),
                    json={"state": "REPORTED_DECLINED", "reason_category": next(iter(DECLINE_REASONS))})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_ASSIGNEE"
    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests/{req}/cancel", headers=colleague, json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_ASSIGNEE"
    with session_scope() as db:
        assert db.get(Opportunity, uuid.UUID(oid)).state != "REPORTED_DECLINED"

    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests/{req}/cancel",
                    headers=as_user("manager@lakeside.demo"), json={"reason": "Asked by mistake"})
    assert r.status_code == 200, r.text


def test_only_credit_and_business_leads_shape_appetite(client, as_user):
    """Appetite Studio: an officer is refused (403); a Credit/Risk lead drafts a mandate on their own products."""
    r = client.post("/api/v1/inst/appetites", headers=as_user("officer@lakeside.demo"),
                    json={"name": "Officer appetite", "product_ids": []})
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED"
    credit = as_user("credit@lakeside.demo")
    own = client.get("/api/v1/inst/products", headers=credit).json()["products"][0]["id"]
    r = client.post("/api/v1/inst/appetites", headers=credit, json={"name": "Credit lead appetite", "product_ids": [own]})
    assert r.status_code == 201, r.text
