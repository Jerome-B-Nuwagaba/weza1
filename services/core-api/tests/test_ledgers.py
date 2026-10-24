"""Evidence ledgers are append-only (TSD §52-53) and the migration history has one head (TSD §80)."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from weza.domains.trust.models import PolicyDecisionLog
from weza.domains.trust.service import record_decision
from weza.platform.db import session_scope

ROOT = Path(__file__).resolve().parents[1]


def _refused(engine, sql: str, params: dict | None = None) -> None:
    with pytest.raises(Exception, match="append-only"):
        with engine.begin() as c:
            c.execute(sa.text(sql), params or {})


def test_the_decision_ledger_and_access_log_cannot_be_changed_or_removed(database):
    with session_scope() as db:
        d = record_decision(db, "TEST_LEDGER", "test", "ledger-1", inputs={"a": 1}, output={"b": 2})
        log = PolicyDecisionLog(actor="TEST:1", action="ledger.test", resource="test:x", result="PERMIT",
                                fields_permitted=[])
        db.add(log)
        db.flush()
        decision_id, log_id = str(d.id), str(log.id)
    engine = sa.create_engine(database)
    _refused(engine, "UPDATE trust.decision SET decision_type='tampered' WHERE id = :id", {"id": decision_id})
    _refused(engine, "DELETE FROM trust.decision WHERE id = :id", {"id": decision_id})
    _refused(engine, "TRUNCATE trust.decision")
    _refused(engine, "UPDATE trust.policy_decision_log SET result='tampered' WHERE id = :id", {"id": log_id})
    _refused(engine, "DELETE FROM trust.policy_decision_log WHERE id = :id", {"id": log_id})
    _refused(engine, "TRUNCATE trust.policy_decision_log")
    with engine.begin() as c:  # and both rows are still there, untouched
        assert c.execute(sa.text("SELECT decision_type FROM trust.decision WHERE id = :id"),
                         {"id": decision_id}).scalar() == "TEST_LEDGER"
        assert c.execute(sa.text("SELECT result FROM trust.policy_decision_log WHERE id = :id"),
                         {"id": log_id}).scalar() == "PERMIT"


def test_the_migration_history_has_exactly_one_head():
    """Two branches that each add a migration produce two heads and a deploy that cannot upgrade. Catch it in CI."""
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"merge the migration branches: heads are {heads}"
