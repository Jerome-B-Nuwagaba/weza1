"""identity.verification_check: CRB identity-check attempts, outcome and consent evidence (new table)

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('verification_check',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('need_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('provider', sa.String(length=24), nullable=False),
    sa.Column('identification_type', sa.String(length=48), nullable=False),
    sa.Column('identifier_index', sa.String(length=64), nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('outcome', sa.String(length=24), nullable=True),
    sa.Column('field_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error_category', sa.String(length=24), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('bureau_enquiry_id', sa.String(length=64), nullable=True),
    sa.Column('bureau_reference', sa.String(length=64), nullable=True),
    sa.Column('bureau_status', sa.String(length=16), nullable=True),
    sa.Column('cost', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('matches', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('consent_version', sa.String(length=20), nullable=False),
    sa.Column('consent_text_hash', sa.String(length=64), nullable=False),
    sa.Column('consent_channel', sa.String(length=16), nullable=False),
    sa.Column('consented_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_verification_check')),
    schema='identity'
    )
    op.create_index(op.f('ix_identity_verification_check_customer_id'), 'verification_check', ['customer_id'],
                    unique=False, schema='identity')
    op.create_index(op.f('ix_identity_verification_check_identifier_index'), 'verification_check',
                    ['identifier_index'], unique=False, schema='identity')
    op.create_index(op.f('ix_identity_verification_check_idempotency_key'), 'verification_check',
                    ['idempotency_key'], unique=False, schema='identity')


def downgrade() -> None:
    op.drop_table('verification_check', schema='identity')
