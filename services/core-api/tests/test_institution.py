"""Institution onboarding graph: apply → verify → users → product (maker-checker) → appetite (simulate, approve)
→ routing → notifications → activate (AT-22…AT-28)."""

import uuid

from tests.helpers import login

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


def test_assistant_answers_from_tools_read_only(client, as_user):
    """AT-38: deterministic assistant routes to permitted tools and never mutates."""
    r = client.post("/api/v1/inst/ask", json={"question": "Show my best SME opportunities today"},
                    headers=as_user("manager@lakeside.demo")).json()
    assert r["tool_calls"][0]["tool"] == "search_opportunities" and r["answer"]
    r = client.post("/api/v1/inst/ask", json={"question": "What sits just outside our appetite?"},
                    headers=as_user("credit@lakeside.demo")).json()
    assert r["tool_calls"][0]["tool"] == "get_near_match_analysis"


def test_outcome_insight_exists_and_appetite_unchanged(client, as_user):
    """AT-40 / BR-004: mismatch insight raised; appetite not altered automatically."""
    h = as_user("credit@lakeside.demo")
    ins = client.get("/api/v1/inst/intelligence/insights", headers=h).json()["insights"]
    assert any(i["kind"] == "APPETITE_OUTCOME_MISMATCH" for i in ins)
    aps = client.get("/api/v1/inst/appetites", headers=h).json()["appetites"]
    assert all(a["active_version"] == 1 for a in aps)
