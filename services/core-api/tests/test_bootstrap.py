"""First-run bootstrap for real (non-demo) environments."""

from sqlalchemy import select

from weza import bootstrap
from weza.domains.identity.models import User
from weza.platform.db import session_scope

FAKE_PASSWORD = "Fake-Bootstrap-Pass-1!"


def test_bootstrap_creates_one_weza_admin_who_can_sign_in(client, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "first.admin@example.test")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", FAKE_PASSWORD)
    assert bootstrap.main([]) == 0
    assert bootstrap.main(["--if-configured"]) == 0  # idempotent
    with session_scope() as db:
        rows = db.execute(select(User).where(User.email == "first.admin@example.test")).scalars().all()
        assert len(rows) == 1 and rows[0].kind == "WEZA" and "WEZA_SUPER" in rows[0].weza_roles
    r = client.post("/api/v1/auth/login", json={"email": "first.admin@example.test", "password": FAKE_PASSWORD})
    assert r.status_code == 200, r.text


def test_bootstrap_without_credentials_creates_nobody(monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    with session_scope() as db:
        before = len(db.execute(select(User.id)).all())
    assert bootstrap.main(["--if-configured"]) == 0
    with session_scope() as db:
        assert len(db.execute(select(User.id)).all()) == before


def test_short_password_is_refused(monkeypatch):
    import pytest

    from weza.platform.errors import ValidationFailed
    with pytest.raises(ValidationFailed):
        bootstrap.create_admin("short@example.test", "Short", "tooshort")
