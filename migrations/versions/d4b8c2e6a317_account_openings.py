"""Account opening balances (kohal, 2026-11-08) - the amount an account held on a chosen day, so the Accounts view counts credits and
debits from that day on. A brand-new table only; nothing existing is changed.

Revision ID: d4b8c2e6a317
Revises: c8f2a6b4d159
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4b8c2e6a317'
down_revision = 'c8f2a6b4d159'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'account_openings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account', sa.String(length=40), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('as_of', sa.Date(), nullable=False),
        sa.Column('updated_by_code', sa.String(length=4), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['updated_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account', name='uq_account_openings_account'),
    )


def downgrade():
    op.drop_table('account_openings')
