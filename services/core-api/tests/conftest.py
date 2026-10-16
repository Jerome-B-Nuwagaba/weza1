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
logging.getLogger("pgserver").setLevel(logging.CRITICAL)


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
                           "OR bucket LIKE 'journey:ip:%' OR bucket LIKE 'login:%'"))
    yield


@pytest.fixture(scope="session")
def app(database):
    from weza.main import create_app
    return create_app(start_worker=False)


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


