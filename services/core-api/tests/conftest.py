"""Test harness: a disposable PostgreSQL database (CI service or local pgserver), migrated with Alembic and
seeded once through the real services. Event delivery is drained explicitly so tests are deterministic."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("RUN_WORKER_INPROCESS", "false")
os.environ.setdefault("OTP_DELIVERY", "display")
os.environ.setdefault("ENV", "test")
os.environ.pop("ANTHROPIC_API_KEY", None)  # tests exercise the deterministic (AI-unavailable) path by default
# A developer's services/core-api/.env may hold REAL channel credentials. Environment variables win over .env, so
# blank them: tests always start in simulator/console mode and opt in with fake values via monkeypatch.
for _name in ("ANTHROPIC_API_KEY", "WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_APP_SECRET",
              "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_API_VERSION", "WHATSAPP_BUSINESS_ACCOUNT_ID", "WHATSAPP_BUSINESS_NUMBER",
              "WHATSAPP_OTP_TEMPLATE_NAME", "WHATSAPP_APP_ID", "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", "SMS_PROVIDER", "SMS_API_KEY", "SMS_USERNAME", "SMS_SENDER_ID", "SMTP_URL",
              "GNUGRID_BASE_URL", "GNUGRID_CLIENT_ID", "GNUGRID_CLIENT_SECRET", "GNUGRID_PI_CODE"):
    os.environ[_name] = ""
os.environ.pop("CRB_JIT_ENABLED", None)  # booleans can't be blank: tests opt in per test (crb_on fixture)
os.environ["GNGRID_USE_MOCK"] = "true"  # never the real, charged bureau in tests
logging.getLogger("pgserver").setLevel(logging.CRITICAL)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """No test may reach Meta or any provider. Tests that exercise outbound calls install their own recorder."""
    import httpx

    def refuse(url, *a, **k):
        raise AssertionError(f"real network call attempted in a test: {str(url).split('?')[0][:60]}")
    monkeypatch.setattr(httpx, "post", refuse)
    monkeypatch.setattr(httpx, "get", refuse)


def _admin_url() -> str:
    url = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if url:
        return url
    import pgserver
    srv = pgserver.get_server(str(ROOT / ".pgdata"), cleanup_mode=None)
    return srv.get_uri().replace("postgresql://", "postgresql+psycopg://")


@pytest.fixture(scope="session", autouse=True)
def database():
    admin = _admin_url()
    base = admin.rsplit("/", 1)[0]
    name = "weza_test"
    eng = sa.create_engine(admin, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(sa.text(f"select pg_terminate_backend(pid) from pg_stat_activity where datname='{name}' "
                          "and pid<>pg_backend_pid()"))
        c.execute(sa.text(f"DROP DATABASE IF EXISTS {name}"))
        c.execute(sa.text(f"CREATE DATABASE {name}"))
    eng.dispose()
    url = f"{base}/{name}"
    os.environ["WEZA_TEST_DATABASE_URL"] = url
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True,
                   env={**os.environ, "WEZA_TEST_DATABASE_URL": url})
    from weza.platform.db import reset_engine
    reset_engine(url)
    from weza.seed import seed
    seed()
    yield url


@pytest.fixture(autouse=True)
def _reset_ip_rate_limits(database):
    """Every test client shares one IP and the same demo logins, so journey/OTP/login limits would accumulate across
    the suite. Reset them per test; tests that exercise rate limiting trip them within a single test."""
    from weza.platform.db import session_scope
    with session_scope() as db:
        db.execute(sa.text("DELETE FROM platform.rate_counter WHERE bucket LIKE 'otp:ip:%' "
                           "OR bucket LIKE 'journey:ip:%' OR bucket LIKE 'login:%' OR bucket LIKE 'apply:%'"))
    yield


@pytest.fixture(scope="session")
def app(database):
    from weza.main import create_app
    return create_app(start_worker=False)


@pytest.fixture()
def clean_market_after():
    """Leave the market the way this test found it.

    The suite shares one seeded database, so a test that leaves live supply behind changes what later tests
    see: a customer who is meant to wait for a match instead matches against the leftover institution. Tests
    that create institutions ask for this fixture and get every institution they created taken back out of
    the market (paused institution, paused product, archived mandate) once the test is done.
    """
    from weza.domains.appetite.models import Appetite
    from weza.domains.institution.models import Institution
    from weza.domains.product.models import Product
    from weza.platform.db import session_scope

    with session_scope() as db:
        before = {str(i.id) for i in db.execute(sa.select(Institution)).scalars()}
    yield
    with session_scope() as db:
        created = [i for i in db.execute(sa.select(Institution)).scalars() if str(i.id) not in before]
        for inst in created:
            db.execute(sa.update(Product).where(Product.institution_id == inst.id).values(status="PAUSED"))
            db.execute(sa.update(Appetite).where(Appetite.institution_id == inst.id)
                       .values(lifecycle_status="ARCHIVED"))
            db.execute(sa.update(Institution).where(Institution.id == inst.id).values(status="PAUSED"))


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def drain():
    from weza.platform.events import drain as _drain
    return _drain


from tests.helpers import Journey, login  # noqa: E402


@pytest.fixture()
def as_user(client):
    def _as(email: str) -> dict:
        return login(client, email)
    return _as


@pytest.fixture()
def journey(client):
    def _start(text: str | None = None, **kw) -> Journey:
        return Journey(client, text, **kw)
    return _start


