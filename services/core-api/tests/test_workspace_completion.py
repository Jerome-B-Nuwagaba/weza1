"""Mandate waiting state (FSD-WAIT-002), Teams and SMS honesty (BRD §20), a person's own mobile number and the daily and
weekly briefs (FSD §34): each checked at the edge where it could silently go wrong."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tests.helpers import login
from tests.test_institution_workspace import PW, _new_institution
from weza.domains.appetite import service as appetite_svc
from weza.domains.appetite.models import Appetite
from weza.domains.identity.models import Membership, User
from weza.domains.institution.models import Institution
from weza.domains.intelligence import briefs
from weza.domains.misc_models import Notification
from weza.domains.notification import service as notif
from weza.domains.notification import teams
from weza.platform.db import session_scope

TEAMS_URL = "https://prod-12.westus.logic.azure.com/workflows/abc/triggers/manual"
MONDAY_NOON = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)  # 12:00 East Africa Time
WEDNESDAY_NOON = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def test_demand_state_reports_waiting_paused_full_and_expired():
    with session_scope() as db:
        ap = db.execute(select(Appetite).where(Appetite.lifecycle_status == "ACTIVE")).scalars().first()
        assert ap is not None
        try:
            ap.capacity_state = "OPEN"
            assert appetite_svc.demand_state(db, ap)["state"] in {"WAITING", "RECEIVING"}
            ap.capacity_state = "FULL"
            assert appetite_svc.demand_state(db, ap)["state"] == "FULL"
            ap.capacity_state = "PAUSED"
            assert appetite_svc.demand_state(db, ap)["state"] == "PAUSED"
            ap.capacity_state, ap.lifecycle_status = "OPEN", "EXPIRED"
            assert appetite_svc.demand_state(db, ap)["state"] == "EXPIRED"
        finally:
            db.rollback()  # the demo mandate is shared by other tests: never keep these changes


def test_teams_address_must_be_a_microsoft_host_and_is_never_returned(client, as_user):
    w = _new_institution(client, as_user)
    bad = client.put("/api/v1/inst/notification-channels", headers=w["admin"],
                     json={"teams_webhook_url": "https://evil.example.com/hook"})
    assert bad.status_code == 422
    ok = client.put("/api/v1/inst/notification-channels", headers=w["admin"], json={"teams_webhook_url": TEAMS_URL})
    assert ok.status_code == 200 and ok.json() == {"teams_configured": True}
    assert TEAMS_URL not in client.get("/api/v1/inst/notification-channels", headers=w["admin"]).text
    off = client.put("/api/v1/inst/notification-channels", headers=w["admin"], json={"teams_webhook_url": None})
    assert off.json() == {"teams_configured": False}
    assert client.post("/api/v1/inst/notification-channels/teams/test", headers=w["admin"]).status_code == 422


def test_only_an_administrator_can_connect_teams(client, as_user):
    w = _new_institution(client, as_user)
    officer = login(client, f"off@w{w['s']}.co.ug", PW)
    r = client.put("/api/v1/inst/notification-channels", headers=officer, json={"teams_webhook_url": TEAMS_URL})
    assert r.status_code == 403


def test_the_teams_test_message_posts_a_card_and_reports_a_refusal(client, as_user, monkeypatch):
    w = _new_institution(client, as_user)
    client.put("/api/v1/inst/notification-channels", headers=w["admin"], json={"teams_webhook_url": TEAMS_URL})
    sent = []
    monkeypatch.setattr(teams, "post", lambda url, title, body="", link=None: sent.append((url, title)))
    assert client.post("/api/v1/inst/notification-channels/teams/test", headers=w["admin"]).json() == {"ok": True}
    assert sent == [(TEAMS_URL, "WEZA test message")]

    def refuse(*a, **k):
        raise teams.TeamsError("Teams refused the message (HTTP 400)")
    monkeypatch.setattr(teams, "post", refuse)
    r = client.post("/api/v1/inst/notification-channels/teams/test", headers=w["admin"])
    assert r.status_code == 422 and "refused" in r.text


def test_my_phone_is_validated_masked_and_removable(client, as_user):
    w = _new_institution(client, as_user)
    h = w["admin"]
    assert client.get("/api/v1/inst/me/phone", headers=h).json() == {"set": False, "masked": None}
    assert client.put("/api/v1/inst/me/phone", headers=h, json={"phone": "12345"}).status_code == 422
    r = client.put("/api/v1/inst/me/phone", headers=h, json={"phone": "0772 123 456"})
    assert r.status_code == 200 and r.json()["set"] is True and "772123456" not in r.text
    assert client.put("/api/v1/inst/me/phone", headers=h, json={"phone": ""}).json()["set"] is False


def test_a_channel_is_usable_only_when_it_can_actually_reach_the_person(client, as_user):
    w = _new_institution(client, as_user)
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == f"off@w{w['s']}.co.ug")).scalar_one()
        assert notif.channel_usable(db, w["id"], user, "in_app") and notif.channel_usable(db, w["id"], user, "email")
        assert not notif.channel_usable(db, w["id"], user, "sms")
        assert not notif.channel_usable(db, w["id"], user, "teams")
        assert not notif.channel_usable(db, w["id"], user, "push")
        user.preferences = {"phone": "+256772123456"}
        assert notif.channel_usable(db, w["id"], user, "sms")
        inst = db.get(Institution, w["id"])
        inst.profile = teams.set_webhook(inst.profile, TEAMS_URL)
        assert notif.channel_usable(db, w["id"], user, "teams")


def _active_institution(client, as_user) -> dict:
    """A new institution that has gone live (briefs are only sent for live institutions)."""
    w = _new_institution(client, as_user)
    with session_scope() as db:
        db.get(Institution, w["id"]).status = "ACTIVE"
    return w


def _briefs_for(inst_id, kind):
    with session_scope() as db:
        return db.execute(select(Notification).where(Notification.institution_id == inst_id,
                                                      Notification.event_type == kind)).scalars().all()


def test_briefs_go_out_once_per_person_and_to_the_right_roles(client, as_user):
    w = _active_institution(client, as_user)
    with session_scope() as db:
        first = briefs.send_due(db, MONDAY_NOON)
    assert first["daily"] >= 3  # administrator, manager and officer
    assert len(_briefs_for(w["id"], "DailyBrief")) == 3
    assert len(_briefs_for(w["id"], "WeeklyBrief")) >= 2  # the executive-level roles only
    with session_scope() as db:
        assert briefs.send_due(db, MONDAY_NOON + timedelta(hours=1)) == {"daily": 0, "weekly": 0}  # safe to repeat
    assert len(_briefs_for(w["id"], "DailyBrief")) == 3


def test_briefs_wait_until_the_morning_and_weekly_is_only_on_mondays(client, as_user):
    w = _active_institution(client, as_user)
    with session_scope() as db:
        assert briefs.send_due(db, datetime(2026, 10, 19, 2, 0, tzinfo=UTC)) == {"daily": 0, "weekly": 0}  # 05:00 EAT
        briefs.send_due(db, WEDNESDAY_NOON)
    assert _briefs_for(w["id"], "WeeklyBrief") == [] and len(_briefs_for(w["id"], "DailyBrief")) == 3


def test_an_officers_brief_covers_only_their_own_work(client, as_user):
    w = _active_institution(client, as_user)
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == f"off@w{w['s']}.co.ug")).scalar_one()
        member = db.execute(select(Membership).where(Membership.user_id == user.id)).scalar_one()
        brief = briefs.daily(db, briefs.actor_for(db, user, member))
    assert brief["body"].startswith(("Nothing new", "You have"))
    assert "Your institution has" not in brief["body"]
