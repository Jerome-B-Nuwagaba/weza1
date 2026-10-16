"""Institution workspace management: users, roles, teams, routing targets, notification preferences and passwords —
including tenant isolation on every id taken from a request. Also covers previously untested institution acceptance
scenarios (AT-30 feed ranking, AT-32 auto-assignment, AT-37 demand suppression, AT-35 radius, reports export)."""

import uuid
from decimal import Decimal

from sqlalchemy import select

from tests.helpers import login
from weza.domains.identity.models import Membership, RefreshToken, User
from weza.domains.institution.models import Institution, Team
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import Opportunity
from weza.domains.trust.models import AuditEvent
from weza.platform.db import session_scope

PW = "Str0ng-Passw0rd!"


def _new_institution(client, as_user) -> dict:
    """A fresh, verified institution with a team, an officer and a manager — isolated from the demo tenants."""
    s = uuid.uuid4().hex[:6]
    r = client.post("/api/v1/institutions/applications", json={
        "legal_name": f"Workspace {s} Ltd", "institution_type": "Fintech Lender", "licence_no": "W-1",
        "regulator": "Other", "representative": {"name": "Rep", "email": f"rep@w{s}.co.ug"},
        "compliance": {"name": "Comp", "email": f"comp@w{s}.co.ug"}, "admin_name": "Admin",
        "admin_email": f"admin@w{s}.co.ug", "admin_password": PW, "accept_terms": True})
    assert r.status_code == 201, r.text
    inst_id = r.json()["institution_id"]
    client.post(f"/api/v1/admin/institutions/{inst_id}/verify", json={"approve": True, "reason": "ok"},
                headers=as_user("ops@weza.demo"))
    admin = login(client, f"admin@w{s}.co.ug", PW)
    team = client.post("/api/v1/inst/teams", json={"name": "Desk"}, headers=admin).json()
    for who, roles in (("off", ["OFFICER"]), ("mgr", ["MANAGER"]), ("biz", ["BUSINESS"])):
        assert client.post("/api/v1/inst/users", headers=admin, json={
            "full_name": who, "email": f"{who}@w{s}.co.ug", "roles": roles, "team_id": team["id"],
            "password": PW}).status_code == 201
    users = {u["email"].split("@")[0]: u for u in client.get("/api/v1/inst/users", headers=admin).json()["users"]}
    return {"s": s, "id": inst_id, "admin": admin, "team": team["id"], "users": users}


def _pearl_team_and_user():
    with session_scope() as db:
        inst = db.execute(select(Institution).where(Institution.display_name == "Pearl SACCO")).scalar_one()
        team = db.execute(select(Team).where(Team.institution_id == inst.id)).scalars().first()
        user = db.execute(select(Membership).where(Membership.institution_id == inst.id)).scalars().first()
        return str(team.id), str(user.user_id)


def test_team_and_user_ids_are_tenant_checked(client, as_user):
    w = _new_institution(client, as_user)
    pearl_team, pearl_user = _pearl_team_and_user()
    r = client.post("/api/v1/inst/users", headers=w["admin"], json={
        "full_name": "Xavier", "email": f"x@w{w['s']}.co.ug", "roles": ["OFFICER"], "team_id": pearl_team,
        "password": PW})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_TEAM"
    off = w["users"]["off"]["id"]
    r = client.patch(f"/api/v1/inst/users/{off}", headers=w["admin"], json={"team_id": pearl_team})
    assert r.json()["error"]["code"] == "UNKNOWN_TEAM"
    r = client.patch(f"/api/v1/inst/users/{off}", headers=w["admin"], json={"roles": []})
    assert r.json()["error"]["code"] == "ROLES_REQUIRED"
    # Another institution's user is invisible
    assert client.patch(f"/api/v1/inst/users/{pearl_user}", headers=w["admin"],
                        json={"status": "DISABLED"}).status_code == 404
    assert client.post(f"/api/v1/inst/users/{pearl_user}/password", headers=w["admin"],
                       json={"new_password": "Another-Str0ng-Pw!"}).status_code == 404
    assert client.patch(f"/api/v1/inst/teams/{pearl_team}", headers=w["admin"], json={"name": "Hijack"}).status_code == 422


def test_roles_can_be_edited_and_teams_renamed_or_removed_safely(client, as_user):
    w = _new_institution(client, as_user)
    off = w["users"]["off"]["id"]
    r = client.patch(f"/api/v1/inst/users/{off}", headers=w["admin"], json={"roles": ["OFFICER", "COMPLIANCE"]})
    assert set(next(u for u in r.json()["users"] if u["id"] == off)["roles"]) == {"OFFICER", "COMPLIANCE"}
    assert client.patch(f"/api/v1/inst/teams/{w['team']}", headers=w["admin"],
                        json={"name": "SME Desk"}).json()["name"] == "SME Desk"
    r = client.delete(f"/api/v1/inst/teams/{w['team']}", headers=w["admin"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "TEAM_IN_USE"
    empty = client.post("/api/v1/inst/teams", json={"name": "Spare"}, headers=w["admin"]).json()
    r = client.delete(f"/api/v1/inst/teams/{empty['id']}", headers=w["admin"])
    assert r.status_code == 200 and all(t["id"] != empty["id"] for t in r.json()["teams"])


def _opportunity_for(inst_id: str, amount=10_000_000) -> uuid.UUID:
    with session_scope() as db:
        o = Opportunity(reference=f"OPP-T{uuid.uuid4().hex[:4].upper()}", idempotency_key=uuid.uuid4().hex,
                        need_id=uuid.uuid4(), customer_id=uuid.uuid4(), institution_id=uuid.UUID(inst_id),
                        product_id=uuid.uuid4(), match_id=uuid.uuid4(), consent_id=uuid.uuid4(), state="ROUTED",
                        amount=Decimal(amount), match_score=80.0, customer_type="SME")
        db.add(o)
        db.flush()
        return o.id


def test_routing_targets_must_be_active_officers_of_this_institution(client, as_user):
    """AT-32 + the cross-tenant fix: a rule can't name an outsider or a non-officer; if a named officer is later
    disabled, work falls back to the team instead of going to someone who can't act on it."""
    w = _new_institution(client, as_user)
    _, pearl_user = _pearl_team_and_user()
    for bad in (pearl_user, w["users"]["biz"]["id"]):  # another tenant's user; a BUSINESS-only user
        r = client.put("/api/v1/inst/routing", headers=w["admin"], json={"rules": [
            {"name": "Named", "conditions": {}, "target_team_id": w["team"], "target_user_id": bad}]})
        assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_ASSIGNEE"
    off, mgr = w["users"]["off"]["id"], w["users"]["mgr"]["id"]
    assert client.put("/api/v1/inst/routing", headers=w["admin"], json={"rules": [
        {"name": "Named", "conditions": {}, "target_team_id": w["team"], "target_user_id": mgr}]}).status_code == 200
    with session_scope() as db:
        a = opp_svc.assign_by_rules(db, db.get(Opportunity, _opportunity_for(w["id"])))
        assert str(a.user_id) == mgr and a.assigned_by == "RULE"
    client.patch(f"/api/v1/inst/users/{mgr}", headers=w["admin"], json={"status": "DISABLED"})
    with session_scope() as db:
        a = opp_svc.assign_by_rules(db, db.get(Opportunity, _opportunity_for(w["id"])))
        assert str(a.user_id) == off  # least-loaded active officer of the rule's team
    # No matching rule → Unassigned queue (and the manager alert event)
    client.put("/api/v1/inst/routing", headers=w["admin"], json={"rules": [
        {"name": "Big only", "conditions": {"min_amount": 900_000_000}, "target_team_id": w["team"]}]})
    with session_scope() as db:
        a = opp_svc.assign_by_rules(db, db.get(Opportunity, _opportunity_for(w["id"])))
        assert a.user_id is None and a.assigned_by == "UNASSIGNED"


def test_paused_appetite_cannot_be_resumed_while_institution_inactive(client, as_user):
    import pytest

    from weza.domains.appetite import service as appetite_svc
    from weza.domains.appetite.models import Appetite
    from weza.domains.identity import service as identity
    from weza.platform.errors import ValidationFailed
    w = _new_institution(client, as_user)  # verified but not activated (CONFIGURING)
    with session_scope() as db:
        ap = Appetite(institution_id=uuid.UUID(w["id"]), name="Paused mandate", lifecycle_status="PAUSED")
        db.add(ap)
        db.flush()
        admin = db.execute(select(User).where(User.email == f"admin@w{w['s']}.co.ug")).scalar_one()
        actor = identity.actor_for_user(db, admin, False)
        with pytest.raises(ValidationFailed) as e:
            appetite_svc.set_lifecycle(db, actor, ap, "ACTIVE", "try resume")
        assert e.value.code == "INSTITUTION_NOT_ACTIVE"
        appetite_svc.set_lifecycle(db, actor, ap, "ARCHIVED", "retire it")
        assert ap.lifecycle_status == "ARCHIVED"


def test_notification_preferences_are_validated(client, as_user):
    w = _new_institution(client, as_user)
    put = lambda prefs: client.put("/api/v1/inst/notification-prefs", headers=w["admin"], json={"prefs": prefs})  # noqa: E731
    assert put([{"event_type": "OpportunityRouted", "min_priority": "LOUD"}]).json()["error"]["code"] == "INVALID_PREF"
    assert put([{"event_type": "OpportunityRouted"}, {"event_type": "OpportunityRouted"}]).status_code == 422
    assert put([{"event_type": "bad type!"}]).status_code == 422
    r = put([{"event_type": "InfoRequestFulfilled", "channels": ["email", "fax"], "min_priority": "HIGH"}])
    pref = r.json()["prefs"][0]
    assert pref["channels"] == ["in_app", "email"] and pref["min_priority"] == "HIGH"  # in_app can't be dropped
    assert "InfoRequestExpired" in r.json()["events"]


def test_password_change_and_admin_reset_end_other_sessions(client, as_user):
    w = _new_institution(client, as_user)
    off_email = f"off@w{w['s']}.co.ug"
    off = login(client, off_email, PW)
    r = client.post("/api/v1/inst/password", headers=off, json={"current_password": "wrong-password-x",
                                                               "new_password": "Brand-New-Passw0rd!"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
    r = client.post("/api/v1/inst/password", headers=off, json={"current_password": PW, "new_password": PW})
    assert r.json()["error"]["code"] == "PASSWORD_REUSED"
    assert client.post("/api/v1/inst/password", headers=off, json={
        "current_password": PW, "new_password": "Brand-New-Passw0rd!"}).status_code == 200
    with session_scope() as db:
        uid = db.execute(select(User.id).where(User.email == off_email)).scalar_one()
        assert all(t.revoked for t in db.execute(select(RefreshToken).where(RefreshToken.user_id == uid)).scalars())
    assert client.post("/api/v1/auth/login", json={"email": off_email, "password": PW}).status_code == 401
    login(client, off_email, "Brand-New-Passw0rd!")
    # Administrator reset
    assert client.post(f"/api/v1/inst/users/{w['users']['off']['id']}/password", headers=w["admin"],
                       json={"new_password": "Temp-Reset-Passw0rd!"}).status_code == 200
    login(client, off_email, "Temp-Reset-Passw0rd!")
    me = client.get("/api/v1/inst/users", headers=w["admin"]).json()
    admin_id = next(u["id"] for u in me["users"] if "INST_ADMIN" in u["roles"])
    assert client.post(f"/api/v1/inst/users/{admin_id}/password", headers=w["admin"], json={
        "new_password": "Self-Reset-Passw0rd!"}).json()["error"]["code"] == "USE_SELF_SERVICE"
    with session_scope() as db:
        actions = set(db.execute(select(AuditEvent.action).where(AuditEvent.object_id == str(uid))).scalars())
        assert {"users.password_changed", "users.password_reset"} <= actions


def test_feed_ranking_is_explained_and_export_is_audited(client, as_user):
    """AT-30: the feed states its ranking factors; the CSV export holds no identity and is audited."""
    h = as_user("manager@lakeside.demo")
    feed = client.get("/api/v1/inst/opportunities?sort=priority", headers=h).json()
    assert "Priority" in feed["ranking"] and feed["items"]
    csv = client.get("/api/v1/inst/reports/export", headers=h)
    assert csv.status_code == 200 and csv.text.startswith("reference,state,amount")
    assert "+256" not in csv.text and "@" not in csv.text
    with session_scope() as db:
        assert db.execute(select(AuditEvent).where(AuditEvent.action == "reports.exported")).scalars().first()


def test_demand_intelligence_suppresses_small_cells_and_radius_explains_near_misses(client, as_user):
    """AT-37 / AT-35: every demand breakdown hides groups under k=5; Radius shows inside / near / outside."""
    h = as_user("credit@lakeside.demo")
    d = client.get("/api/v1/inst/intelligence/demand?days=365", headers=h).json()
    for key in ("by_region", "by_district", "by_sector", "by_customer_type", "by_purpose", "ticket_sizes"):
        assert all(v >= 5 for v in d[key].values()), key
    radius = client.get("/api/v1/inst/intelligence/radius", headers=h).json()
    assert radius["appetites"] and {"inside", "near", "outside"} <= set(radius["appetites"][0])
