"""WEZA V1 foundation: primary contact, appetite mandate, verified phone on the journey.

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- institution: the one contact WEZA reaches first
    op.add_column("contact", sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
                  schema="institution")
    op.create_index("uq_contact_primary_per_institution", "contact", ["institution_id"], unique=True,
                    schema="institution", postgresql_where=sa.text("is_primary"))

    # ---- appetite: the mandate as first-class dimensions
    op.add_column("appetite_version", sa.Column("customer_types", postgresql.ARRAY(sa.String()),
                                                 nullable=False, server_default="{}"), schema="appetite")
    op.add_column("appetite_version", sa.Column("sectors", postgresql.ARRAY(sa.String()),
                                                 nullable=False, server_default="{}"), schema="appetite")
    op.add_column("appetite_version", sa.Column("regions", postgresql.ARRAY(sa.String()),
                                                 nullable=False, server_default="{}"), schema="appetite")
    op.add_column("appetite_version", sa.Column("min_amount", sa.Numeric(precision=18, scale=2), nullable=True),
                  schema="appetite")
    op.add_column("appetite_version", sa.Column("max_amount", sa.Numeric(precision=18, scale=2), nullable=True),
                  schema="appetite")
    op.add_column("appetite_version", sa.Column("min_business_age_months", sa.Integer(), nullable=True),
                  schema="appetite")

    # ---- need: whether this journey's phone number has been proven reachable
    op.add_column("financial_need", sa.Column("phone_verified", sa.Boolean(), nullable=False,
                                               server_default=sa.false()), schema="need")
    op.add_column("financial_need", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
                  schema="need")
    op.add_column("financial_need", sa.Column("phone_verification_method", sa.String(length=24), nullable=True),
                  schema="need")


def downgrade() -> None:
    op.drop_column("financial_need", "phone_verification_method", schema="need")
    op.drop_column("financial_need", "phone_verified_at", schema="need")
    op.drop_column("financial_need", "phone_verified", schema="need")
    op.drop_column("appetite_version", "min_business_age_months", schema="appetite")
    op.drop_column("appetite_version", "max_amount", schema="appetite")
    op.drop_column("appetite_version", "min_amount", schema="appetite")
    op.drop_column("appetite_version", "regions", schema="appetite")
    op.drop_column("appetite_version", "sectors", schema="appetite")
    op.drop_column("appetite_version", "customer_types", schema="appetite")
    op.drop_index("uq_contact_primary_per_institution", table_name="contact", schema="institution")
    op.drop_column("contact", "is_primary", schema="institution")
