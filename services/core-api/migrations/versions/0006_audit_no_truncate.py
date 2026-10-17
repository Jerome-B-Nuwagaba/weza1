"""audit ledger: also refuse TRUNCATE (the row trigger only covers UPDATE and DELETE)

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON trust.audit_event
        FOR EACH STATEMENT EXECUTE FUNCTION trust.audit_append_only();
    """)


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS audit_event_no_truncate ON trust.audit_event')
