"""WhatsApp outbound idempotency and early delivery receipt reconciliation.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_message",
        sa.Column("idempotency_key", sa.String(length=180), nullable=True),
        schema="notification",
    )
    op.create_unique_constraint(
        "uq_channel_message_idempotency_key",
        "channel_message",
        ["idempotency_key"],
        schema="notification",
    )
    op.create_table(
        "whatsapp_status_receipt",
        sa.Column("provider_message_id", sa.String(length=128), nullable=False),
        sa.Column("provider_status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider_message_id", name="pk_whatsapp_status_receipt"),
        schema="notification",
    )
    op.create_index(
        "ix_notification_whatsapp_status_receipt_received_at",
        "whatsapp_status_receipt",
        ["received_at"],
        unique=False,
        schema="notification",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_whatsapp_status_receipt_received_at",
        table_name="whatsapp_status_receipt",
        schema="notification",
    )
    op.drop_table("whatsapp_status_receipt", schema="notification")
    op.drop_constraint(
        "uq_channel_message_idempotency_key",
        "channel_message",
        type_="unique",
        schema="notification",
    )
    op.drop_column("channel_message", "idempotency_key", schema="notification")
