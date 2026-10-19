"""notification.whatsapp_inbox: per-message processing attempts and retry time (additive columns only)

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('whatsapp_inbox', sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
                  schema='notification')
    op.add_column('whatsapp_inbox', sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
                  schema='notification')


def downgrade() -> None:
    op.drop_column('whatsapp_inbox', 'next_attempt_at', schema='notification')
    op.drop_column('whatsapp_inbox', 'attempts', schema='notification')
