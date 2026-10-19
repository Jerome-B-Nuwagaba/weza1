"""Constrain information request states, preserving deployed 0002 history.

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

STATUS = postgresql.ENUM("OPEN", "FULFILLED", "CANCELLED", "EXPIRED",
                         name="info_request_status", schema="opportunity")


def upgrade() -> None:
    STATUS.create(op.get_bind(), checkfirst=True)
    op.alter_column("info_request", "status", schema="opportunity", existing_type=sa.String(12),
                    type_=STATUS, existing_nullable=False,
                    postgresql_using="status::opportunity.info_request_status")


def downgrade() -> None:
    op.alter_column("info_request", "status", schema="opportunity", existing_type=STATUS,
                    type_=sa.String(12), existing_nullable=False, postgresql_using="status::text")
    STATUS.drop(op.get_bind(), checkfirst=True)
