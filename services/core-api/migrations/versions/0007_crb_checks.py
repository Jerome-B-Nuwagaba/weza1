"""Just-In-Time gnuGRID CRB checks; widen fact.verification_state for VERIFIED_THIRD_PARTY

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('crb_check',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('institution_id', sa.UUID(), nullable=False),
    sa.Column('match_id', sa.UUID(), nullable=True),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('session_id', sa.String(length=120), nullable=False),
    sa.Column('challenge_id', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('provider_ref', sa.String(length=120), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crb_check')),
    schema='consent'
    )
    op.create_index(op.f('ix_consent_crb_check_customer_id'), 'crb_check', ['customer_id'], unique=False,
                    schema='consent')
    op.create_index(op.f('ix_consent_crb_check_institution_id'), 'crb_check', ['institution_id'], unique=False,
                    schema='consent')
    op.alter_column('fact', 'verification_state', type_=sa.String(length=24), existing_type=sa.String(length=16),
                    schema='customer')


def downgrade() -> None:
    op.alter_column('fact', 'verification_state', type_=sa.String(length=16), existing_type=sa.String(length=24),
                    schema='customer')
    op.drop_index(op.f('ix_consent_crb_check_institution_id'), table_name='crb_check', schema='consent')
    op.drop_index(op.f('ix_consent_crb_check_customer_id'), table_name='crb_check', schema='consent')
    op.drop_table('crb_check', schema='consent')
