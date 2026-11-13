"""Fooding starting balance and date (kohal, 2026-11-13) - the balance a person's fooding held at the start of a chosen day, set from
the employee form. Two new nullable columns only; nothing existing is changed.

Revision ID: b6a0e3d8f592
Revises: a5f9d2e7c481
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6a0e3d8f592'
down_revision = 'a5f9d2e7c481'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('fooding_accounts', sa.Column('opening_amount', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('fooding_accounts', sa.Column('opening_date', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('fooding_accounts', 'opening_date')
    op.drop_column('fooding_accounts', 'opening_amount')
