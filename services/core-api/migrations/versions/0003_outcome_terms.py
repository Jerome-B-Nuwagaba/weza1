"""indicative terms on institution-reported approvals

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

COLUMNS = [
    sa.Column('tenor_months', sa.Integer(), nullable=True),
    sa.Column('interest_rate', sa.Numeric(precision=6, scale=3), nullable=True),
    sa.Column('rate_period', sa.String(length=8), nullable=True),
    sa.Column('fees', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('monthly_repayment', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('conditions', sa.Text(), nullable=True),
    sa.Column('terms_valid_until', sa.Date(), nullable=True),
]


def upgrade() -> None:
    for c in COLUMNS:
        op.add_column('outcome', c, schema='opportunity')


def downgrade() -> None:
    for c in reversed(COLUMNS):
        op.drop_column('outcome', c.name, schema='opportunity')
