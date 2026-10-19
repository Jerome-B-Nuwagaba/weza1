"""Tenant isolation, exhaustively: for EVERY institution role and EVERY by-id institution route, another tenant's
record must be indistinguishable from a record that doesn't exist — same status, never a success, never a server
error — whether or not the role holds the route's permission. Lists never contain another tenant's ids."""

import uuid

import pytest
from sqlalchemy import select

from tests.helpers import idem
from tests.test_institution import pearl  # noqa: F401 — fixture by name
from weza.domains.identity.models import Membership
from weza.domains.institution.models import Institution, Team
from weza.domains.misc_models import Notification
from weza.platform.db import session_scope

LAKESIDE_ROLES = ["admin", "exec", "business", "credit", "manager", "officer", "compliance"]


@pytest.fixture
def foreign(pearl):  # noqa: F811
    """Pearl SACCO records of every kind a by-id route accepts."""
    with session_scope() as db:
        inst = db.execute(select(Institution.id).where(Institution.display_name == "Pearl SACCO")).scalar_one()
        user = db.execute(select(Membership.user_id).where(Membership.institution_id == inst)).scalars().first()
        team = db.execute(select(Team.id).where(Team.institution_id == inst)).scalars().first()
        note = Notification(event_type="Test", recipient_type="USER", recipient_id=user, institution_id=inst,
                            channel="in_app", priority="NORMAL", title="Pearl-only")
        db.add(note)
        db.flush()
        return {**pearl, "user": str(user), "team": str(team) if team else None, "notification": str(note.id)}


def _routes(f: dict) -> list[tuple[str, str, dict | None]]:
    some_user = str(uuid.uuid4())
    out = [
        ("get", "/inst/opportunities/{opp}", None),
        ("post", "/inst/opportunities/{opp}/status", {"state": "CONTACTED"}),
        ("post", "/inst/opportunities/{opp}/outcome", {"state": "WITHDRAWN"}),
        ("post", "/inst/opportunities/{opp}/assign", {"user_id": some_user}),
        ("post", "/inst/opportunities/{opp}/info-requests", {"kind": "QUESTION", "message": "Hello?"}),
        ("post", "/inst/opportunities/{opp}/info-requests/" + str(uuid.uuid4()) + "/cancel", None),
        ("delete", "/inst/opportunities/{opp}/info-requests/" + str(uuid.uuid4()), None),
        ("get", "/inst/opportunities/{opp}/documents/" + str(uuid.uuid4()), None),
        ("get", "/inst/products/{product}", None),
        ("put", "/inst/products/{product}", {"name": "Hijacked", "family": "SME_GROWTH",
                                             "terms": {"min_amount": 1, "max_amount": 2}}),
        ("post", "/inst/products/{product}/submit", None),
        ("post", "/inst/products/{product}/review", {"approve": True}),
        ("post", "/inst/products/{product}/status", {"status": "PAUSED", "reason": "hijack"}),
        ("get", "/inst/appetites/{appetite}", None),
        ("put", "/inst/appetites/{appetite}", {"name": "Hijacked", "product_ids": []}),
        ("post", "/inst/appetites/{appetite}/simulate", None),
        ("post", "/inst/appetites/{appetite}/review", {"approve": True}),
        ("post", "/inst/appetites/{appetite}/status", {"status": "PAUSED", "reason": "hijack"}),
        ("post", "/inst/appetites/{appetite}/capacity", {"override": "PAUSED", "reason": "hijack"}),
        ("post", "/inst/intelligence/insights/{insight}", {"status": "DISMISSED", "note": "hijack"}),
        ("post", "/inst/previews/{preview}/interest", {"state": "INTERESTED"}),
        ("post", "/inst/billing/events/{event}/dispute", {"reason": "DUPLICATE",
                                                          "description": "Not our opportunity at all."}),
        ("patch", "/inst/users/{user}", {"roles": ["OFFICER"]}),
        ("post", "/inst/users/{user}/password", {"password": "Hijack!Passw0rd"}),
        ("post", "/inst/notifications/{notification}/ack", None),
    ]
    if f.get("team"):
        out += [("patch", "/inst/teams/{team}", {"name": "Hijacked"}), ("delete", "/inst/teams/{team}", None)]
    return out


@pytest.mark.parametrize("role", LAKESIDE_ROLES)
def test_another_tenants_ids_are_indistinguishable_from_missing_ones_for_every_role(client, as_user, foreign, role):
    headers = as_user(f"{role}@lakeside.demo")
    for method, tpl, body in _routes(foreign):
        theirs = "/api/v1" + tpl.format(**foreign)
        random = "/api/v1" + tpl.format(**{k: str(uuid.uuid4()) for k in foreign})
        r1 = client.request(method, theirs, headers=idem(headers), json=body)
        r2 = client.request(method, random, headers=idem(headers), json=body)
        where = f"{role}: {method.upper()} {tpl}"
        assert r1.status_code < 500 and r2.status_code < 500, f"{where} -> server error {r1.text[:200]}"
        assert r1.status_code >= 400, f"{where} acted on another tenant's record: {r1.status_code} {r1.text[:200]}"
        assert r1.status_code == r2.status_code, (f"{where} reveals that the record exists: {r1.status_code} for "
                                                  f"theirs vs {r2.status_code} for a missing id")


LISTS = ["/inst/workspace", "/inst/users", "/inst/products", "/inst/appetites", "/inst/routing",
         "/inst/notification-prefs", "/inst/command-centre", "/inst/opportunities", "/inst/my-day", "/inst/previews",
         "/inst/team", "/inst/intelligence/radius", "/inst/intelligence/demand", "/inst/intelligence/reason-signals",
         "/inst/intelligence/product-gaps", "/inst/intelligence/insights", "/inst/reports/outcomes",
         "/inst/reports/export", "/inst/billing", "/inst/audit", "/inst/notifications"]


@pytest.mark.parametrize("role", LAKESIDE_ROLES)
def test_no_list_or_report_contains_another_tenants_records(client, as_user, foreign, role):
    headers = as_user(f"{role}@lakeside.demo")
    theirs = {v for v in foreign.values() if v}
    for path in LISTS:
        r = client.get("/api/v1" + path, headers=headers)
        assert r.status_code < 500, f"{role} GET {path} -> {r.status_code}"
        if r.status_code == 200:
            assert not any(i in r.text for i in theirs), f"{role} GET {path} contains a Pearl SACCO record"
            assert "Pearl SACCO" not in r.text and "Pearl-only" not in r.text, f"{role} GET {path} names Pearl"


def test_bad_input_is_a_validation_error_not_a_crash(client, as_user):
    admin = as_user("admin@lakeside.demo")
    assert client.get("/api/v1/inst/audit?limit=-1", headers=admin).status_code == 422
    assert client.get("/api/v1/inst/opportunities?limit=0", headers=as_user("manager@lakeside.demo")).status_code == 422
    r = client.get("/api/v1/inst/opportunities?state=%00", headers=as_user("manager@lakeside.demo"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED"
    r = client.post("/api/v1/inst/teams", headers=admin, json={"name": "Bad\x00name"})
    assert r.status_code == 422
    r = client.post(f"/api/v1/inst/opportunities/{uuid.uuid4()}/assign", headers=admin, json={"user_id": "nope"})
    assert r.status_code == 422
