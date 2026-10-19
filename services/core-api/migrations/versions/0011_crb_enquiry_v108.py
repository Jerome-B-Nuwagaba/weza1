"""crb_check: consent evidence and GnuGrid v1.08 enquiry identifiers; the consent-code handshake becomes optional

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None

S = 'consent'
NEW = [
    ('consent_version', sa.String(length=20)), ('consent_text_hash', sa.String(length=64)),
    ('consent_channel', sa.String(length=16)), ('consented_at', sa.DateTime(timezone=True)),
    ('enquiry_id', sa.String(length=64)), ('enquiry_reference', sa.String(length=64)),
    ('bureau_status', sa.String(length=16)), ('individual_id', sa.String(length=32)),
    ('cost', sa.Numeric(precision=14, scale=2)), ('error_category', sa.String(length=24)),
]


def upgrade() -> None:
    for name, type_ in NEW:
        op.add_column('crb_check', sa.Column(name, type_, nullable=True), schema=S)
    for name, type_ in (('session_id', sa.String(length=120)), ('challenge_id', sa.String(length=120)),
                        ('expires_at', sa.DateTime(timezone=True))):
        op.alter_column('crb_check', name, existing_type=type_, nullable=True, schema=S)


def downgrade() -> None:
    for name, _ in reversed(NEW):
        op.drop_column('crb_check', name, schema=S)
