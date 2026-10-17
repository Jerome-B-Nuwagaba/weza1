"""notification.whatsapp_inbox: durable, deduplicated inbound WhatsApp messages (new table)

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('whatsapp_inbox',
    sa.Column('provider_message_id', sa.String(length=128), nullable=False),
    sa.Column('msg_type', sa.String(length=24), nullable=False),
    sa.Column('phone_index', sa.String(length=64), nullable=False),
    sa.Column('payload_enc', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('reason', sa.String(length=40), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_whatsapp_inbox')),
    sa.UniqueConstraint('provider_message_id', name=op.f('uq_whatsapp_inbox_provider_message_id')),
    schema='notification'
    )
    op.create_index(op.f('ix_notification_whatsapp_inbox_phone_index'), 'whatsapp_inbox', ['phone_index'], unique=False, schema='notification')
    op.create_index(op.f('ix_notification_whatsapp_inbox_status'), 'whatsapp_inbox', ['status'], unique=False, schema='notification')
    op.create_index(op.f('ix_notification_whatsapp_inbox_received_at'), 'whatsapp_inbox', ['received_at'], unique=False, schema='notification')


def downgrade() -> None:
    op.drop_table('whatsapp_inbox', schema='notification')
