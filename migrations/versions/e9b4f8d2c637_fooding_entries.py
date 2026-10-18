"""fooding_entries table (kohal, 2026-10-18): the human-readable record behind a FoodingAccount's own
allotted_total/deducted_total - an "allot" entry (amount + how it was paid) when the admin/accountant tops
someone up, an "expense" entry (amount + how it was paid + what it was for) when a daily-wage worker spends
some of their own balance on travel or anything else, not just the automatic daily food deduction.

Revision ID: e9b4f8d2c637
Revises: d4f7c2a9b813
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'e9b4f8d2c637'
down_revision = 'd4f7c2a9b813'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fooding_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('payment_mode', sa.String(length=20), nullable=False),
        sa.Column('purpose', sa.String(length=200), server_default='', nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['fooding_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fooding_entries_account_id', 'fooding_entries', ['account_id'])


def downgrade():
    op.drop_index('ix_fooding_entries_account_id', table_name='fooding_entries')
    op.drop_table('fooding_entries')
