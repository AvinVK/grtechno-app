"""One row per day the automatic fooding deduction was taken (kohal, 2026-11-02: "when i click on that 1800, it
should open everyday expense of 200 with date") - a new table, nothing existing is touched. Days taken before this
existed aren't in it; the register rebuilds those from the allotment dates and marks them as estimated.

Revision ID: f7c1d5a9e264
Revises: e6a0c4f8b153
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'f7c1d5a9e264'
down_revision = 'e6a0c4f8b153'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fooding_deductions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['fooding_accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fooding_deductions_account_id', 'fooding_deductions', ['account_id'])


def downgrade():
    op.drop_index('ix_fooding_deductions_account_id', table_name='fooding_deductions')
    op.drop_table('fooding_deductions')
