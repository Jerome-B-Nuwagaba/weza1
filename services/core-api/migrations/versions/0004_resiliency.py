"""resiliency v1.1: info-request fact keys, preview reason signals, notification backoff, audit IP

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('info_request', sa.Column('fact_key', sa.String(length=60), nullable=True), schema='opportunity')
    op.add_column('notification', sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
                  schema='notification')
    # The append-only trigger fires on UPDATE/DELETE only, so adding a nullable column is allowed.
    op.add_column('audit_event', sa.Column('ip', sa.String(length=64), nullable=True), schema='trust')
    op.create_table('reason_signal',
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('preview_id', sa.UUID(), nullable=False),
    sa.Column('need_id', sa.UUID(), nullable=False),
    sa.Column('reason', sa.String(length=30), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reason_signal')),
    sa.UniqueConstraint('preview_id', name=op.f('uq_reason_signal_preview_id')),
    schema='opportunity'
    )
    op.create_index(op.f('ix_opportunity_reason_signal_institution_id'), 'reason_signal', ['institution_id'],
                    unique=False, schema='opportunity')
    op.create_index(op.f('ix_opportunity_reason_signal_need_id'), 'reason_signal', ['need_id'], unique=False,
                    schema='opportunity')
    op.create_index(op.f('ix_opportunity_reason_signal_created_at'), 'reason_signal', ['created_at'], unique=False,
                    schema='opportunity')


def downgrade() -> None:
    op.drop_index(op.f('ix_opportunity_reason_signal_created_at'), table_name='reason_signal', schema='opportunity')
    op.drop_index(op.f('ix_opportunity_reason_signal_need_id'), table_name='reason_signal', schema='opportunity')
    op.drop_index(op.f('ix_opportunity_reason_signal_institution_id'), table_name='reason_signal',
                  schema='opportunity')
    op.drop_table('reason_signal', schema='opportunity')
    op.drop_column('audit_event', 'ip', schema='trust')
    op.drop_column('notification', 'next_attempt_at', schema='notification')
    op.drop_column('info_request', 'fact_key', schema='opportunity')
