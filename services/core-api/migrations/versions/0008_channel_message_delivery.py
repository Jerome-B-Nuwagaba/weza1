"""channel_message: provider delivery tracking columns (additive, nullable)

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('channel_message', sa.Column('provider_message_id', sa.String(length=128), nullable=True), schema='notification')
    op.add_column('channel_message', sa.Column('provider_status', sa.String(length=16), nullable=True), schema='notification')
    op.add_column('channel_message', sa.Column('error_code', sa.String(length=32), nullable=True), schema='notification')
    op.add_column('channel_message', sa.Column('status_at', sa.DateTime(timezone=True), nullable=True), schema='notification')
    op.create_index(op.f('ix_notification_channel_message_provider_message_id'), 'channel_message', ['provider_message_id'], unique=False, schema='notification')


def downgrade() -> None:
    op.drop_index(op.f('ix_notification_channel_message_provider_message_id'), table_name='channel_message', schema='notification')
    op.drop_column('channel_message', 'status_at', schema='notification')
    op.drop_column('channel_message', 'error_code', schema='notification')
    op.drop_column('channel_message', 'provider_status', schema='notification')
    op.drop_column('channel_message', 'provider_message_id', schema='notification')
