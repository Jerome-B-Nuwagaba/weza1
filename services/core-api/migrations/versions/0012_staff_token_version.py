"""Invalidate existing staff sessions when passwords change.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("token_version", sa.Integer(), server_default="1", nullable=False),
                  schema="identity")


def downgrade() -> None:
    op.drop_column("user", "token_version", schema="identity")
