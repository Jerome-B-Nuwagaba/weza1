"""Auditable agent/tool execution steps.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_step",
        sa.Column("agent", sa.String(length=60), nullable=False),
        sa.Column("tool", sa.String(length=80), nullable=False),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column("result_status", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_step"),
        schema="analytics",
    )
    op.create_index("ix_analytics_agent_step_agent", "agent_step", ["agent"], schema="analytics")
    op.create_index("ix_analytics_agent_step_subject", "agent_step", ["subject"], schema="analytics")
    op.create_index("ix_analytics_agent_step_created_at", "agent_step", ["created_at"], schema="analytics")


def downgrade() -> None:
    op.drop_table("agent_step", schema="analytics")
