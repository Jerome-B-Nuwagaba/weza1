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
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_TRANSITION"
    ev = _audits("review.dismiss", resolved_obj := next(i for i in resolved if i["id"] == item_id)["object_id"])
    assert len(ev) == 1 and ev[0].before["status"] == "OPEN" and ev[0].after["status"] == "RESOLVED"
    assert ev[0].reason == "Facts reconciled" and ev[0].actor_display and resolved_obj
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
    again = client.post(f"{API}/integrity/{case_id}/decide", json={"result": "BLOCK", "note": "Changed mind"},
                        headers=ops)
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_TRANSITION"
    ev = _audits("integrity.decided", case_id)
    assert len(ev) == 1 and ev[0].after == {"state": "DECIDED", "result": "ALLOW"} and ev[0].reason == "Genuine customer"
    assert client.post(f"{API}/integrity/{uuid.uuid4()}/decide", json={"result": "ALLOW", "note": "Unknown"},
                       headers=ops).status_code == 404
    assert client.post(f"{API}/integrity/{case_id}/decide", json={"result": "ALLOW", "note": "Not mine"},
                       headers=as_user("commercial@weza.demo")).status_code == 403


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


def test_editing_a_contract_keeps_its_billing_threshold_and_other_rules(client, as_user):
    """Changing only the price must not reset what counts as billable (the editor used to send 60 every time)."""
    from weza.domains.commercial import service as commercial
    comm = as_user("commercial@weza.demo")
    row = lambda r: next(x for x in r.json()["institutions"] if x["institution"] == "Kijani Microfinance")  # noqa: E731
    kijani = row(client.get(f"{API}/commercial", headers=comm))
    inst_id = uuid.UUID(kijani["institution_id"])
    with session_scope() as db:
        c = commercial.active_contract(db, inst_id)
        original = dict(c.qualified_definition or {})
        c.qualified_definition = {**original, "min_match_score": 71, "min_verification": "IDENTITY"}
    shown = row(client.get(f"{API}/commercial", headers=comm))["contract"]
    assert shown["min_match_score"] == 71  # the editor starts from the real value
    r = client.put(f"{API}/contracts/{inst_id}", json={**shown, "opportunity_price": 31_000}, headers=comm)
    assert r.status_code == 200 and row(r)["contract"]["min_match_score"] == 71
    with session_scope() as db:
        assert commercial.active_contract(db, inst_id).qualified_definition["min_verification"] == "IDENTITY"
        commercial.active_contract(db, inst_id).qualified_definition = original  # leave the seed as it was


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


def test_vault_lookup_trims_reason_and_audits_denied_attempts(client, as_user):
    ops, comm = as_user("ops@weza.demo"), as_user("commercial@weza.demo")
    assert client.post(f"{API}/customers/lookup", json={"phone": "0772123456", "reason": "      "},
                       headers=ops).status_code == 422
    r = client.post(f"{API}/customers/lookup", json={"phone": "0700000002", "reason": "  Status call  "}, headers=ops)
    assert r.status_code == 200
    r = client.post(f"{API}/customers/lookup", json={"phone": "0700000003", "reason": "Curious about a customer"},
                    headers=comm)
    assert r.status_code == 403
    with session_scope() as db:
        rows = db.execute(select(AuditEvent).where(AuditEvent.action.in_(["vault.lookup", "vault.lookup_denied"]))
                          .order_by(AuditEvent.at.desc()).limit(2)).scalars().all()
        assert [(a.action, a.reason) for a in rows] == [("vault.lookup_denied", "Curious about a customer"),
                                                       ("vault.lookup", "Status call")]
        assert "0700000003" not in str(rows[0].after)  # the phone number is never written to the audit row


def test_admin_can_only_pause_or_resume_supply(client, as_user):
    """09-api: products & appetites (pause). Archiving or expiring stays with the institution (BR-004)."""
    ops = as_user("ops@weza.demo")
    inst = next(i for i in client.get(f"{API}/institutions", headers=ops).json()["institutions"]
                if i["display_name"] == "Lakeside Bank")
    detail = client.get(f"{API}/institutions/{inst['id']}", headers=ops).json()
    pid = next(p["id"] for p in detail["products"] if p["status"] == "ACTIVE")
    aid = next(a["id"] for a in detail["appetites"] if a["status"] == "ACTIVE")
    for kind, item_id in (("products", pid), ("appetites", aid)):
        for to in ("ARCHIVED", "EXPIRED", "DRAFT"):
            r = client.post(f"{API}/{kind}/{item_id}/status", json={"status": to, "reason": "Not allowed"}, headers=ops)
            assert r.status_code == 422, (kind, to)
        # Resuming something already active is an invalid transition
        r = client.post(f"{API}/{kind}/{item_id}/status", json={"status": "ACTIVE", "reason": "Already active"},
                        headers=ops)
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TRANSITION", kind
        assert client.post(f"{API}/{kind}/{item_id}/status", json={"status": "PAUSED", "reason": "Not mine"},
                           headers=as_user("commercial@weza.demo")).status_code == 403


def test_kill_switch_values_are_validated(client, as_user):
    admin = as_user("admin@weza.demo")
    for key, value in (("pause_all_routing", {}), ("pause_all_routing", {"on": "yes"}),
                       ("pause_billing_events", {"on": True, "extra": 1}), ("ai_mode", {"mode": "AVAILABLE", "x": 1}),
                       ("disabled_channels", {"channels": ["fax"]}), ("disabled_channels", {"channels": "web"}),
                       ("disabled_channels", {"channels": ["sms", "sms"]})):
        r = client.post(f"{API}/kill-switches", json={"key": key, "value": value, "reason": "Validation"}, headers=admin)
        assert r.status_code == 422, (key, value)
    for value in ({"channels": ["sms"]}, {"channels": []}):
        assert client.post(f"{API}/kill-switches", json={"key": "disabled_channels", "value": value,
                                                         "reason": "Drill"}, headers=admin).status_code == 200


def test_dispute_decision_needs_reason_and_is_final(client, as_user):
    """FSD §40, §42; blueprint C3: OPEN → UNDER_REVIEW → DECIDED → CLOSED; a decided dispute is never re-decided."""
    from decimal import Decimal

    from weza.domains.commercial.models import CommercialEvent, Dispute
    comm = as_user("commercial@weza.demo")
    inst_id = next(i["id"] for i in client.get(f"{API}/institutions", headers=comm).json()["institutions"]
                   if i["display_name"] == "Pearl SACCO")
    with session_scope() as db:
        ev = CommercialEvent(idempotency_key=f"test:{uuid.uuid4()}", institution_id=uuid.UUID(inst_id),
                             kind="QUALIFIED_OPPORTUNITY", amount=Decimal("25000"), currency="UGX", status="DISPUTED",
                             billing_period="2026-10")
        db.add(ev)
        db.flush()
        d = Dispute(commercial_event_id=ev.id, institution_id=ev.institution_id, reason="OTHER",
                    description="Customer was already ours", state="OPEN", history=[])
        db.add(d)
        db.flush()
        dispute_id = str(d.id)
    move = f"{API}/disputes/{dispute_id}/move"
    assert client.post(move, json={"state": "UNDER_REVIEW"}, headers=as_user("ops@weza.demo")).status_code == 403
    skip = client.post(move, json={"state": "DECIDED", "decision": "CHARGE_VALID", "note": "Skipping review"},
                       headers=comm)
    assert skip.status_code == 409  # OPEN cannot jump straight to DECIDED
    assert client.post(move, json={"state": "UNDER_REVIEW"}, headers=comm).status_code == 200
    r = client.post(move, json={"state": "DECIDED", "decision": "CHARGE_VALID", "note": "   "}, headers=comm)
    assert r.status_code == 422  # a decision needs its reason and evidence
    r = client.post(move, json={"state": "DECIDED", "decision": "CHARGE_VALID", "note": "Not an existing customer"},
                    headers=comm)
    assert r.status_code == 200
    again = client.post(move, json={"state": "DECIDED", "decision": "CHARGE_REVERSED", "note": "Changed mind"},
                        headers=comm)
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_TRANSITION"
    ev = _audits("billing.dispute_decided", dispute_id)
    assert len(ev) == 1 and ev[0].reason == "Not an existing customer"


def test_control_centre_reports_active_controls(client, as_user):
    """Blueprint A-01: queues and kill-switch status, including paused supply."""
    d = client.get(f"{API}/overview", headers=as_user("ops@weza.demo")).json()
    assert set(d["kill_switches"]) == {"pause_all_routing", "pause_billing_events", "disabled_channels", "ai_mode"}
    assert set(d["paused_supply"]) == {"products", "mandates"} and "queues" in d and "institutions_by_status" in d


def test_pausing_institution_removes_it_from_options_and_is_audited(client, journey, drain, as_user):
    """AT-47 / AT-50 (FSD FR-040, TSD §75): pause institution → removed from options, market re-cleared, audited."""
    from tests.helpers import SME_ANSWERS
    from weza.domains.matching.models import Match
    ops = as_user("ops@weza.demo")
    inst_id = next(i["id"] for i in client.get(f"{API}/institutions", headers=ops).json()["institutions"]
                   if i["display_name"] == "Lakeside Bank")
    status = f"{API}/institutions/{inst_id}/status"
    assert client.post(status, json={"status": "PAUSED", "reason": "Not mine"},
                       headers=as_user("commercial@weza.demo")).status_code == 403
    r = client.post(status, json={"status": "PAUSED", "reason": "Complaint investigation"}, headers=ops)
    assert r.status_code == 200 and r.json()["status"] == "PAUSED"
    try:
        drain()
        with session_scope() as db:
            live = db.execute(select(Match).where(Match.institution_id == uuid.UUID(inst_id),
                                                  Match.state.in_(["RANKED", "PRESENTED"]))).scalars().all()
            assert live == []  # re-clearing withdrew every open option for the paused institution
        j = journey("I need UGX 30 million to expand my pharmacy.")
        j.send(action="confirm")
        j.verify("0772100088")
        j.answer_profile({**SME_ANSWERS, "identity.nin": "CM0772100088AB"})
        offered = [o["institution"] for c in j.cards("options") for o in c["options"]]
        assert "Lakeside Bank" not in offered
        ev = [a for a in _audits_for(inst_id) if a.after and a.after.get("status") == "PAUSED"]
        assert ev and ev[-1].reason == "Complaint investigation" and ev[-1].before["status"] == "ACTIVE"
    finally:
        client.post(status, json={"status": "ACTIVE", "reason": "Investigation closed"}, headers=ops)
        drain()
    assert client.get(f"{API}/institutions/{inst_id}", headers=ops).json()["status"] == "ACTIVE"


def _audits_for(object_id: str) -> list[AuditEvent]:
    with session_scope() as db:
        rows = db.execute(select(AuditEvent).where(AuditEvent.object_id == object_id)
                          .order_by(AuditEvent.at)).scalars().all()
        db.expunge_all()
        return rows


def test_admin_changes_emit_catalogued_events(client, as_user):
    """08-runtime-events §5 (audit topic): ConfigChanged for configuration, PrivilegedAccess for vault access."""
    from weza.platform.models import OutboxEvent
    admin, ops, comm = as_user("admin@weza.demo"), as_user("ops@weza.demo"), as_user("commercial@weza.demo")
    flags = {f["key"]: f["enabled"] for f in client.get(f"{API}/config", headers=admin).json()["flags"]}
    for v in (not flags["matching.shadow"], flags["matching.shadow"]):
        client.post(f"{API}/flags", json={"key": "matching.shadow", "enabled": v, "reason": "Event check"}, headers=admin)
    client.post(f"{API}/customers/lookup", json={"phone": "0700000004", "reason": "Customer called in"}, headers=ops)
    client.post(f"{API}/customers/lookup", json={"phone": "0700000005", "reason": "Customer called in"}, headers=comm)
    with session_scope() as db:
        recent = db.execute(select(OutboxEvent).where(OutboxEvent.topic == "audit")
                            .order_by(OutboxEvent.occurred_at.desc()).limit(4)).scalars().all()
        got = [(e.event_type, e.data.get("outcome") or e.data.get("enabled")) for e in reversed(recent)]
        assert got == [("ConfigChanged", not flags["matching.shadow"]), ("ConfigChanged", flags["matching.shadow"]),
                       ("PrivilegedAccess", "NOT_FOUND"), ("PrivilegedAccess", "DENIED")]
        assert all("0700000" not in str(e.data) for e in recent)  # no phone numbers in event payloads
