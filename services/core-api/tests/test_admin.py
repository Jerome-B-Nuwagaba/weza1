"""WEZA Admin (FSD §41; blueprint A-01…A-13): role separation, verification, Human Control Centre, integrity,
commercial contracts, vault lookup, configuration and kill switches — every change audited with a reason."""

import uuid

import pytest
from sqlalchemy import select

from weza.domains.misc_models import IntegrityCase, ReviewItem
from weza.domains.trust.models import AuditEvent
from weza.platform.db import session_scope

PW = "Str0ng-Passw0rd!"
API = "/api/v1/admin"
_TOKENS: dict[str, dict] = {}


@pytest.fixture()
def as_user(client):
    """Sign each account in once: the suite shares the per-email sign-in rate limit with other test modules."""
    from tests.helpers import login

    def _as(email: str) -> dict:
        if email not in _TOKENS:
            _TOKENS[email] = login(client, email)
        return _TOKENS[email]
    return _as


def _apply(client) -> str:
    suffix = uuid.uuid4().hex[:6]
    r = client.post("/api/v1/institutions/applications", json={
        "legal_name": f"Admin Test {suffix} Ltd", "institution_type": "Fintech Lender", "licence_no": "T-2",
        "regulator": "Other", "representative": {"name": "Rep", "email": f"rep@a{suffix}.co.ug"},
        "compliance": {"name": "Comp", "email": f"comp@a{suffix}.co.ug"}, "admin_name": "Admin",
        "admin_email": f"admin@a{suffix}.co.ug", "admin_password": PW, "accept_terms": True})
    assert r.status_code == 201, r.text
    return r.json()["institution_id"]


def _audits(action: str, object_id: str) -> list[AuditEvent]:
    with session_scope() as db:
        rows = db.execute(select(AuditEvent).where(AuditEvent.action == action,
                                                   AuditEvent.object_id == object_id)).scalars().all()
        db.expunge_all()
        return rows


def _review_item(kind: str = "FACT_CONFLICT") -> str:
    with session_scope() as db:
        item = ReviewItem(kind=kind, title="Test item", object_type="need", object_id=str(uuid.uuid4()),
                          dedupe_key=f"test:{uuid.uuid4()}")
        db.add(item)
        db.flush()
        return str(item.id)


# ------------------------------------------------------------------ access


def test_admin_read_open_to_all_weza_roles_only(client, as_user):
    for email in ("admin@weza.demo", "ops@weza.demo", "commercial@weza.demo"):
        h = as_user(email)
        for path in ("/overview", "/institutions", "/market", "/review", "/integrity", "/disputes", "/commercial",
                     "/audit", "/deliveries", "/loops", "/config", "/users"):
            assert client.get(API + path, headers=h).status_code == 200, (email, path)
    assert client.get(API + "/overview").status_code == 401
    r = client.get(API + "/overview", headers=as_user("admin@lakeside.demo"))
    assert r.status_code == 403  # institution administrators never reach WEZA admin


def test_role_separation_on_writes(client, as_user):
    comm, ops = as_user("commercial@weza.demo"), as_user("ops@weza.demo")
    inst_id = next(i["id"] for i in client.get(f"{API}/institutions", headers=ops).json()["institutions"]
                   if i["display_name"] == "Nile Fintech")  # awaiting verification in the seed
    # Commercial cannot verify institutions, run network controls, look up customers or change config
    assert client.post(f"{API}/institutions/{inst_id}/verify", json={"approve": True, "reason": "Looks fine"},
                       headers=comm).status_code == 403
    assert client.post(f"{API}/kill-switches", json={"key": "pause_all_routing", "value": {"on": True},
                                                     "reason": "nope"}, headers=comm).status_code == 403
    assert client.post(f"{API}/customers/lookup", json={"phone": "0772123456", "reason": "Customer called"},
                       headers=comm).status_code == 403
    # Ops cannot change configuration or commercial terms
    assert client.post(f"{API}/flags", json={"key": "matching.shadow", "enabled": True, "reason": "Try it"},
                       headers=ops).status_code == 403
    assert client.post(f"{API}/kill-switches", json={"key": "ai_mode", "value": {"mode": "DEGRADED"},
                                                     "reason": "nope"}, headers=ops).status_code == 403
    assert client.put(f"{API}/contracts/{inst_id}", json={"plan": "X", "subscription_fee": 0, "included_opportunities": 0,
                                                          "opportunity_price": 0}, headers=ops).status_code == 403


# ------------------------------------------------------------------ verification (A-02)


def test_verification_approve_and_reject_are_audited(client, as_user):
    ops = as_user("ops@weza.demo")
    approve_id, reject_id = _apply(client), _apply(client)
    r = client.post(f"{API}/institutions/{approve_id}/verify", json={"approve": True, "reason": "Licence checked"},
                    headers=ops)
    assert r.status_code == 200 and r.json()["status"] == "CONFIGURING"
    r = client.post(f"{API}/institutions/{reject_id}/verify", json={"approve": False, "reason": "Licence not found"},
                    headers=ops)
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    assert client.post(f"{API}/institutions/{reject_id}/verify", json={"approve": True, "reason": ""},
                       headers=ops).status_code == 422  # reason is mandatory
    assert client.get(f"{API}/institutions/{uuid.uuid4()}", headers=ops).status_code == 404


# ------------------------------------------------------------------ Human Control Centre (A-06)


def test_review_item_resolves_once(client, as_user):
    ops = as_user("ops@weza.demo")
    item_id = _review_item()
    r = client.post(f"{API}/review/{item_id}/resolve", json={"action": "dismiss", "note": "Facts reconciled"},
                    headers=ops)
    assert r.status_code == 200
    assert item_id not in {i["id"] for i in r.json()["items"]}
    resolved = client.get(f"{API}/review?status=RESOLVED", headers=ops).json()["items"]
    assert next(i for i in resolved if i["id"] == item_id)["resolution"] == "dismiss: Facts reconciled"
    # A resolved item cannot be acted on again (no double release / replay)
    again = client.post(f"{API}/review/{item_id}/resolve", json={"action": "dismiss", "note": "Second go"}, headers=ops)
    assert again.status_code == 422
    assert client.post(f"{API}/review/{uuid.uuid4()}/resolve", json={"action": "dismiss", "note": "x" * 5},
                       headers=ops).status_code == 404
    assert client.post(f"{API}/review/{_review_item()}/resolve", json={"action": "dismiss", "note": "x" * 5},
                       headers=as_user("commercial@weza.demo")).status_code == 403


# ------------------------------------------------------------------ integrity (A-07)


def test_integrity_case_decided_once(client, as_user):
    ops = as_user("ops@weza.demo")
    with session_scope() as db:
        case = IntegrityCase(subject_type="customer", subject_id=str(uuid.uuid4()), score=55, risk_state="REVIEW",
                             signals=["velocity"])
        db.add(case)
        db.flush()
        case_id = str(case.id)
    r = client.post(f"{API}/integrity/{case_id}/decide", json={"result": "ALLOW", "note": "Genuine customer"},
                    headers=ops)
    assert r.status_code == 200
    c = next(x for x in r.json()["cases"] if x["id"] == case_id)
    assert c["state"] == "DECIDED" and c["result"] == "ALLOW"
    assert client.post(f"{API}/integrity/{case_id}/decide", json={"result": "BLOCK", "note": "Changed mind"},
                       headers=ops).status_code == 422
    assert _audits("integrity.decided", case_id)


# ------------------------------------------------------------------ commercial (A-09)


def test_contract_replaces_previous_and_rejects_unknown_institution(client, as_user):
    comm = as_user("commercial@weza.demo")
    lakeside = next(i for i in client.get(f"{API}/institutions", headers=comm).json()["institutions"]
                    if i["display_name"] == "Lakeside Bank")
    body = {"plan": "GROWTH", "subscription_fee": 1_500_000, "included_opportunities": 40, "opportunity_price": 25_000}
    r = client.put(f"{API}/contracts/{lakeside['id']}", json=body, headers=comm)
    assert r.status_code == 200
    row = next(x for x in r.json()["institutions"] if x["institution_id"] == lakeside["id"])
    assert row["contract"]["plan"] == "GROWTH" and row["contract"]["included_opportunities"] == 40
    assert client.put(f"{API}/contracts/{uuid.uuid4()}", json=body, headers=comm).status_code == 404


# ------------------------------------------------------------------ customer support (A-05)


def test_vault_lookup_requires_reason_and_is_audited(client, as_user):
    ops = as_user("ops@weza.demo")
    assert client.post(f"{API}/customers/lookup", json={"phone": "0772123456", "reason": "hi"},
                       headers=ops).status_code == 422
    r = client.post(f"{API}/customers/lookup", json={"phone": "0700000001", "reason": "Customer called about status"},
                    headers=ops)
    assert r.status_code == 200 and r.json() == {"found": False}
    with session_scope() as db:
        last = db.execute(select(AuditEvent).where(AuditEvent.action == "vault.lookup")
                          .order_by(AuditEvent.at.desc()).limit(1)).scalar_one()
        assert last.reason == "Customer called about status"


# ------------------------------------------------------------------ configuration (A-13)


def test_config_changes_are_validated_and_audited(client, as_user):
    admin = as_user("admin@weza.demo")
    assert client.post(f"{API}/kill-switches", json={"key": "self_destruct", "value": {}, "reason": "test"},
                       headers=admin).status_code == 422
    assert client.post(f"{API}/kill-switches", json={"key": "ai_mode", "value": {"mode": "BROKEN"}, "reason": "test"},
                       headers=admin).status_code == 422
    r = client.post(f"{API}/kill-switches", json={"key": "ai_mode", "value": {"mode": "DEGRADED"},
                                                  "reason": "Provider latency"}, headers=admin)
    assert r.status_code == 200
    ks = {k["key"]: k for k in r.json()["kill_switches"]}
    assert ks["ai_mode"]["value"] == {"mode": "DEGRADED"} and ks["ai_mode"]["reason"] == "Provider latency"
    client.post(f"{API}/kill-switches", json={"key": "ai_mode", "value": {"mode": "AVAILABLE"}, "reason": "Recovered"},
                headers=admin)
    assert len(_audits("kill_switch.changed", "ai_mode")) >= 2

    before = client.get(f"{API}/config", headers=admin).json()["match_weights"]
    bad = {"product_fit": 0.5, "appetite_fit": 0.5, "preference_fit": 0.5, "readiness": 0, "capacity_fit": 0}
    assert client.post(f"{API}/config/match-weights", json={"weights": bad, "note": "bad"},
                       headers=admin).status_code == 422
    r = client.post(f"{API}/config/match-weights", json={"weights": before["data"], "note": "Republish same"},
                    headers=admin)
    assert r.status_code == 200 and r.json()["match_weights"]["version"] == before["version"] + 1


# ------------------------------------------------------------------ consent templates & question paths (A-13)

NEW_TEXT = ("By agreeing, you allow WEZA to share the information listed below with {institution} so that they can "
            "contact you about your financing request. WEZA is not a lender. You can withdraw at any time.")


@pytest.fixture()
def restore_consent_template():
    """Tests share one database; put the seeded consent version back so other suites see what they expect."""
    from weza.domains.consent.models import ConsentTemplate
    with session_scope() as db:
        original = {t.id: t.status for t in db.execute(select(ConsentTemplate)).scalars()}
    yield
    with session_scope() as db:
        for t in db.execute(select(ConsentTemplate)).scalars():
            if t.id in original:
                t.status = original[t.id]
            else:
                db.delete(t)


def test_consent_template_publish_versions_and_retires(client, as_user, restore_consent_template):
    admin, ops = as_user("admin@weza.demo"), as_user("ops@weza.demo")
    before = client.get(f"{API}/config", headers=admin).json()
    body = {"title": "Share my request with {institution}", "text": NEW_TEXT, "reason": "Legal review Q4"}
    assert client.post(f"{API}/config/consent-template", json=body, headers=ops).status_code == 403
    for bad in ({**body, "text": NEW_TEXT.replace("{institution}", "the lender")},   # institution must be named
                {**body, "text": NEW_TEXT + " {customer}"},                           # unknown placeholder
                {**body, "title": before["consent_template"]["title"], "text": before["consent_template"]["text"]},
                {**body, "reason": ""}):
        assert client.post(f"{API}/config/consent-template", json=bad, headers=admin).status_code == 422
    r = client.post(f"{API}/config/consent-template", json=body, headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["consent_template"]["text"] == NEW_TEXT
    assert d["consent_template"]["version"] != before["consent_template"]["version"]
    statuses = {h["version"]: h["status"] for h in d["consent_history"]}
    assert statuses[before["consent_template"]["version"]] == "RETIRED"
    assert statuses[d["consent_template"]["version"]] == "PUBLISHED"
    ev = _audits("consent_template.published", next(
        str(t.id) for t in _templates() if t.version == d["consent_template"]["version"]))
    assert ev and ev[0].reason == "Legal review Q4"


def _templates():
    from weza.domains.consent.models import ConsentTemplate
    with session_scope() as db:
        rows = db.execute(select(ConsentTemplate)).scalars().all()
        db.expunge_all()
        return rows


def test_customer_mid_consent_when_new_version_published(client, journey, as_user, restore_consent_template):
    """A customer shown the old text must not be recorded as agreeing to the new one."""
    from tests.helpers import SME_ANSWERS
    j = journey("I need UGX 30 million to expand my pharmacy.")
    j.send(action="confirm")
    j.verify("0772100077")
    j.answer_profile({**SME_ANSWERS, "identity.nin": "CM0772100077AB"})
    opt = next(o for o in j.cards("options")[0]["options"] if o["readiness"] == "READY")
    j.send(action="select", value=opt["match_id"])
    old_tpl = j.cards("consent")[0]["template_id"]
    client.post(f"{API}/config/consent-template", json={"title": "Share my request with {institution}",
                                                        "text": NEW_TEXT, "reason": "Legal review"},
                headers=as_user("admin@weza.demo"))
    r = client.post(f"/api/v1/journeys/{j.id}/messages", json={"action": "agree", "value": old_tpl}, headers=j.headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONSENT_TEMPLATE_STALE"
    from weza.domains.consent.models import Consent
    with session_scope() as db:
        assert db.execute(select(Consent).where(Consent.match_id == uuid.UUID(opt["match_id"]))).first() is None
    # The journey is not stuck: going back and selecting again shows the new text
    j.send(action="decline")
    assert j.node == "PRESENT_OPTIONS"
    j.send(action="select", value=opt["match_id"])
    new = j.cards("consent")[0]
    assert new["template_id"] != old_tpl and "WEZA is not a lender" in new["text"]


def test_config_shows_question_paths(client, as_user):
    d = client.get(f"{API}/config", headers=as_user("ops@weza.demo")).json()
    assert d["question_paths"]["version"] >= 1 and d["question_paths"]["data"]


def test_flag_change_requires_reason_and_is_audited(client, as_user):
    admin = as_user("admin@weza.demo")
    assert client.post(f"{API}/flags", json={"key": "matching.shadow", "enabled": True},
                       headers=admin).status_code == 422
    flags = {f["key"]: f["enabled"] for f in client.get(f"{API}/config", headers=admin).json()["flags"]}
    for value, reason in ((not flags["matching.shadow"], "Compare algorithms"), (flags["matching.shadow"], "Restore")):
        assert client.post(f"{API}/flags", json={"key": "matching.shadow", "enabled": value, "reason": reason},
                           headers=admin).status_code == 200
    last = _audits("flag.changed", "matching.shadow")
    assert {a.reason for a in last} >= {"Compare algorithms", "Restore"}


def test_pausing_product_or_appetite_requires_step_up_mfa(client, as_user, monkeypatch):
    """Blueprint 10 §10: every kill switch, including Pause Product and Pause Mandate, requires step-up MFA."""
    from weza.config import get_settings
    ops = as_user("ops@weza.demo")  # signed in without MFA
    inst = client.get(f"{API}/institutions", headers=ops).json()["institutions"]
    detail = client.get(f"{API}/institutions/{next(i['id'] for i in inst if i['display_name'] == 'Lakeside Bank')}",
                        headers=ops).json()
    monkeypatch.setattr(get_settings(), "mfa_enforced", True)
    for kind, item in (("products", detail["products"][0]), ("appetites", detail["appetites"][0])):
        r = client.post(f"{API}/{kind}/{item['id']}/status", json={"status": "PAUSED", "reason": "Drill"}, headers=ops)
        assert r.status_code == 403 and r.json()["error"]["code"] == "MFA_STEP_UP_REQUIRED", kind
