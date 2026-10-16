"""institution → customer information requests

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('info_request',
    sa.Column('opportunity_id', sa.UUID(), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('doc_type', sa.String(length=40), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('response_text', sa.Text(), nullable=True),
    sa.Column('document_id', sa.UUID(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_info_request')),
    schema='opportunity'
    )
    op.create_index('ix_info_request_opp_status', 'info_request', ['opportunity_id', 'status'], unique=False,
                    schema='opportunity')
    op.create_index(op.f('ix_opportunity_info_request_institution_id'), 'info_request', ['institution_id'],
                    unique=False, schema='opportunity')
    op.create_index(op.f('ix_opportunity_info_request_customer_id'), 'info_request', ['customer_id'], unique=False,
                    schema='opportunity')


def downgrade() -> None:
    op.drop_index(op.f('ix_opportunity_info_request_customer_id'), table_name='info_request', schema='opportunity')
    op.drop_index(op.f('ix_opportunity_info_request_institution_id'), table_name='info_request', schema='opportunity')
    op.drop_index('ix_info_request_opp_status', table_name='info_request', schema='opportunity')
    op.drop_table('info_request', schema='opportunity')
