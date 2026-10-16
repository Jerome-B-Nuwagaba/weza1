"""identity checks against an external registry (gnuGRID)

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('identity_check',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('check_type', sa.String(length=16), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('name_match', sa.Boolean(), nullable=True),
    sa.Column('dob_match', sa.Boolean(), nullable=True),
    sa.Column('provider_ref', sa.String(length=120), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_identity_check')),
    schema='customer'
    )
    op.create_index(op.f('ix_customer_identity_check_customer_id'), 'identity_check', ['customer_id'], unique=False,
                    schema='customer')


def downgrade() -> None:
    op.drop_index(op.f('ix_customer_identity_check_customer_id'), table_name='identity_check', schema='customer')
    op.drop_table('identity_check', schema='customer')
