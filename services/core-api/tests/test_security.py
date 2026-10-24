"""Trust plane: tenant isolation, disclosure gateway, preview allow-list, redaction, audit, error contract
(AT-SEC-01…06, AT-31, AT-48, AT-49, AT-API-01)."""

import json
import logging
import re
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select, text

from tests.helpers import opp_for
from weza.consumers import preview_payload
from weza.domains.identity.models import User
from weza.domains.matching.models import Match
from weza.domains.need.models import FinancialNeed
from weza.domains.opportunity.models import Assignment, Opportunity
from weza.platform.db import session_scope
from weza.platform.logging import JsonFormatter, redact


def test_cross_tenant_access_is_404(client, as_user):
    """AT-SEC-01: Institution A cannot see that Institution B's opportunity exists."""
    opp_id, _ = opp_for("Pearl SACCO")
    r = client.get(f"/api/v1/inst/opportunities/{opp_id}", headers=as_user("manager@lakeside.demo"))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_assigned_officer_sees_consented_fields_unassigned_officer_does_not(client, as_user):
    """AT-SEC-02 / TSD §29: disclosure depends on relationship + consent, enforced server-side."""
    opp_id, owner = opp_for("Lakeside Bank")
    r = client.get(f"/api/v1/inst/opportunities/{opp_id}", headers=as_user(owner))
    assert r.status_code == 200
    cust = r.json()["customer"]
    assert cust["restricted"] is False, cust
    assert cust["fields"].get("phone", "").startswith("+256")
    # An officer sees only their own assigned work: a colleague's opportunity is "not found", like another tenant's
    other = next(e for e in ("officer@lakeside.demo", "officer2@lakeside.demo", "asset@lakeside.demo") if e != owner)
    r2 = client.get(f"/api/v1/inst/opportunities/{opp_id}", headers=as_user(other))
    assert r2.status_code == 404
    # Executives get opportunity intelligence but never identity
    r3 = client.get(f"/api/v1/inst/opportunities/{opp_id}", headers=as_user("exec@lakeside.demo"))
    assert r3.json()["customer"]["fields"] == {}


def test_consent_withdrawal_hides_identity(client, as_user, journey):
    """AT-18: after withdrawal, new views no longer disclose identifiable fields."""
    from tests.helpers import SME_ANSWERS
    j = journey("I need UGX 20 million to buy stock for my pharmacy")
    j.send(action="confirm")
    j.verify("0772200001")
    j.answer_profile({**SME_ANSWERS, "identity.nin": "CM0772200001AB"})
    opt = next(o for o in j.cards("options")[0]["options"] if o["institution"] == "Lakeside Bank")
    j.send(action="select", value=opt["match_id"])
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    ref = j.cards("submitted")[0]["reference"]
    from weza.platform.events import drain
    drain()
    with session_scope() as db:
        o = db.execute(select(Opportunity).where(Opportunity.reference == ref)).scalar_one()
        owner = db.get(User, db.get(Assignment, o.id).user_id).email
        oid = str(o.id)
    h = as_user(owner)
    assert client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()["customer"]["fields"]
    consents = client.get("/api/v1/me/consents", headers=j.customer_headers).json()["consents"]
    r = client.post(f"/api/v1/me/consents/{consents[0]['id']}/withdraw", headers=j.customer_headers)
    assert r.status_code == 200
    after = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
    assert after["customer"]["fields"] == {} and after["customer"]["restriction_reason"] == "consent_not_valid"


def test_customers_own_words_are_shown_only_with_permitted_disclosure(client, as_user, journey):
    """The free-text purpose may name the customer: feed cards and restricted views show only the category label."""
    from tests.helpers import routed_to_lakeside
    _, oid, owner = routed_to_lakeside(journey, "0772470002")
    words = "restock Nakato Pharmacy, Plot 12 Kampala Road, call 0772470002"
    with session_scope() as db:
        o = db.get(Opportunity, uuid.UUID(oid))
        o.snapshot = {**o.snapshot, "need": {**o.snapshot["need"], "purpose": words}}
    permitted = client.get(f"/api/v1/inst/opportunities/{oid}", headers=as_user(owner)).json()
    assert permitted["customer"]["restricted"] is False and permitted["snapshot"]["need"]["purpose"] == words
    restricted = client.get(f"/api/v1/inst/opportunities/{oid}", headers=as_user("exec@lakeside.demo"))
    assert restricted.status_code == 200 and restricted.json()["customer"]["restricted"] is True
    feed = client.get("/api/v1/inst/opportunities", headers=as_user("manager@lakeside.demo")).text
    for body in (restricted.text, feed, json.dumps(permitted["need"])):
        assert "Nakato" not in body and "0772470002" not in body and "Kampala Road" not in body


def test_preview_payload_is_non_identifiable():
    """AT-31 / FSD-PRV-001: preview never exposes direct identifiers."""
    with session_scope() as db:
        m = db.execute(select(Match).where(Match.state.in_(["RANKED", "PRESENTED", "SELECTED"])).limit(1)).scalar_one()
        need = db.get(FinancialNeed, m.need_id)
        payload = preview_payload(need, m)
    assert set(payload) <= {"customer_type", "sector", "region", "purpose_category", "amount_band", "match_band",
                            "readiness"}
    assert "district" not in payload


def test_staff_endpoints_require_auth_and_role(client, as_user):
    assert client.get("/api/v1/inst/command-centre").status_code == 401
    r = client.get("/api/v1/admin/overview", headers=as_user("manager@lakeside.demo"))
    assert r.status_code == 403
    r = client.post("/api/v1/inst/products", json={"name": "Officer product", "family": "SME_GROWTH", "terms": {"min_amount": 1, "max_amount": 2}},
                    headers=as_user("officer@lakeside.demo"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED"


def test_error_contract_shape(client):
    """AT-API-01 / TSD §59."""
    r = client.post("/api/v1/journeys", json={"channel": "fax"})
    body = r.json()
    assert r.status_code == 422
    assert set(body["error"]) >= {"code", "message", "correlation_id", "retryable", "details"}
    assert r.headers["X-Correlation-ID"] == body["error"]["correlation_id"] or body["error"]["correlation_id"]


def test_login_rate_limit_and_lockout(client):
    """AT-SEC-05: brute-force controls."""
    codes = [client.post("/api/v1/auth/login", json={"email": "compliance@pearl.demo", "password": "wrong-password-x"}
                         ).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5
    r = client.post("/api/v1/auth/login", json={"email": "compliance@pearl.demo", "password": "WezaDemo!2026"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_log_redaction():
    """AT-SEC-06 / TSD §66."""
    rec = logging.LogRecord("t", logging.INFO, "", 0, "call +256772123456 nin CM1234567890AB a@b.co", None, None)
    rec.data = {"phone": "+256772123456", "otp": "123456", "amount": 5}
    out = JsonFormatter().format(rec)
    assert "772123456" not in out and "CM1234567890AB" not in out and "123456" not in out and "a@b.co" not in out
    assert redact({"nested": {"password": "x"}}) == {"nested": {"password": "[REDACTED]"}}


def test_audit_is_append_only(database):
    """AT-48 / TSD §53: audit rows cannot be updated or deleted. Uses its own row so it never passes vacuously."""
    from weza.domains.trust.service import audit
    from weza.platform.context import SYSTEM
    with session_scope() as db:
        ev = audit(db, SYSTEM, "test.append_only", "test", "x")
        db.flush()
        row_id = str(ev.id)
    eng = sa.create_engine(database)
    with pytest.raises(Exception, match="append-only"):
        with eng.begin() as c:
            c.execute(sa.text("UPDATE trust.audit_event SET action='tampered' WHERE id = :id"), {"id": row_id})
    with pytest.raises(Exception, match="append-only"):
        with eng.begin() as c:
            c.execute(sa.text("DELETE FROM trust.audit_event WHERE id = :id"), {"id": row_id})
    with pytest.raises(Exception, match="append-only"):
        with eng.begin() as c:
            c.execute(sa.text("TRUNCATE trust.audit_event"))
    with eng.begin() as c:
        assert c.execute(sa.text("SELECT count(*) FROM trust.audit_event WHERE id = :id"), {"id": row_id}).scalar() == 1


def test_zero_core_integration_boundary():
    """AT-49 / FR-039: the only outbound HTTP calls are the customer channels (WhatsApp, SMS), the AI provider, the
    identity registry used to verify applicants and the credit bureau (gnuGRID) — there is no connector to any institution core banking,
    CRM, LOS or database."""
    root = Path(__file__).resolve().parents[1] / "weza"
    offenders = []
    for f in root.rglob("*.py"):
        src = f.read_text(encoding="utf8")
        if re.search(r"httpx\.(get|post|put|request|Client)|requests\.|urllib\.request", src):
            offenders.append(f.relative_to(root).as_posix())
    assert sorted(offenders) == ["domains/notification/service.py", "domains/verification/adapters.py",
                                 "integrations/gnugrid.py"], offenders
    assert "graph.facebook.com" in (root / "domains/notification/service.py").read_text(encoding="utf8")


def test_every_network_touchpoint_is_known():
    """AT-49, wider net: any socket, database driver/engine, mail or SDK client outside this allow-list fails, so a
    connector to an institution's core banking, LOS or CRM can't slip in without a deliberate review."""
    root = Path(__file__).resolve().parents[1] / "weza"
    allowed = {
        "platform/db.py": "WEZA's own PostgreSQL",
        "domains/customer/documents.py": "ClamAV malware scanner (clamd socket)",
        "domains/notification/service.py": "customer channels: Meta WhatsApp, SMS gateways",
        "domains/notification/whatsapp_media.py": "customer channel: media customers send on WhatsApp (Meta Graph)",
        "domains/verification/adapters.py": "identity registry (gnuGRID)",
        "integrations/gnugrid.py": "credit bureau (gnuGRID CRB), Just-In-Time at lender selection",
        "domains/intelligence/ai.py": "AI provider (Anthropic)",
    }
    pattern = (r"\bsocket\.(create_connection|socket)\b|create_engine\(|\bpsycopg2?\.connect|\b(pyodbc|pymssql|cx_Oracle|"
               r"oracledb|mysql\.connector|pymysql|pymongo|ldap3|zeep|paramiko|ftplib|smtplib|grpc)\b|"
               r"\bimport (anthropic|openai|httpx|requests|aiohttp)\b|urllib\.request|httpx\.")
    found = {f.relative_to(root).as_posix() for f in root.rglob("*.py") if re.search(pattern, f.read_text(encoding="utf8"))}
    assert found <= set(allowed), f"unreviewed network access in {sorted(found - set(allowed))}"


def test_tests_never_use_real_channel_credentials_or_network():
    """A developer's .env may hold real Meta credentials: the harness blanks them and blocks outbound HTTP."""
    import httpx

    from weza.config import get_settings
    s = get_settings()
    assert not (s.whatsapp_send_ready or s.whatsapp_webhook_ready or s.sms_ready)
    with pytest.raises(AssertionError, match="real network call"):
        httpx.post("https://graph.facebook.com/v25.0/x/messages", json={})


def test_sign_in_attempts_per_address_are_capped_and_the_cap_is_configurable(client, monkeypatch):
    """50 a quarter-hour by default; the browser-test container raises it, and production refuses a high value."""
    from weza.config import Settings, get_settings
    from weza.domains.identity import service as identity
    from weza.platform.errors import RateLimited
    ip = "203.0.113.77"
    monkeypatch.setattr(get_settings(), "login_ip_limit", 3)
    with session_scope() as db:
        db.execute(text("DELETE FROM platform.rate_counter WHERE bucket LIKE 'login:%'"))
    for i in range(3):
        with session_scope() as db, pytest.raises(Exception) as err:
            identity.login(db, f"nobody{i}@example.invalid", "x" * 12, ip=ip)
        assert not isinstance(err.value, RateLimited)  # refused for the password, not for the address
    with pytest.raises(RateLimited), session_scope() as db:
        identity.login(db, "nobody9@example.invalid", "x" * 12, ip=ip)
    with session_scope() as db:
        db.execute(text("DELETE FROM platform.rate_counter WHERE bucket LIKE 'login:%'"))
    assert Settings().login_ip_limit == 50
    assert any("LOGIN_IP_LIMIT" in p for p in Settings(login_ip_limit=1000).production_problems())
    assert not any("LOGIN_IP_LIMIT" in p for p in Settings(login_ip_limit=50).production_problems())
