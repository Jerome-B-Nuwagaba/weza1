"""decision ledger and access-decision log: append-only, like the audit ledger (TSD §52, §53)

The audit ledger already refuses UPDATE, DELETE and TRUNCATE (0001, 0006). The decision ledger (why a match, routing or
policy decision was made) and the data-access decision log (who was shown what, and why) are evidence of the same kind
and must not be editable through normal workflows either. Nothing in the application changes or removes their rows.

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

TABLES = ("decision", "policy_decision_log")


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION trust.ledger_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON trust.{table}
            FOR EACH ROW EXECUTE FUNCTION trust.ledger_append_only();
        """)
        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON trust.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION trust.ledger_append_only();
        """)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_change ON trust.{table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON trust.{table}")
    op.execute("DROP FUNCTION IF EXISTS trust.ledger_append_only()")
