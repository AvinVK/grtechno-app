"""Commission paid in parts (kohal, 2026-11-08) - each part of a commission actually paid out, with the account it came from.
A brand-new table only; nothing existing is changed.

Revision ID: a7e2c5f9d641
Revises: f6d1a4c8e539
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7e2c5f9d641'
down_revision = 'f6d1a4c8e539'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'commission_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('expense_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('paid_date', sa.Date(), nullable=False),
        sa.Column('payment_account', sa.String(length=40), nullable=False, server_default=''),
        sa.Column('note', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['expense_id'], ['project_expenses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_commission_payments_expense_id'), 'commission_payments', ['expense_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_commission_payments_expense_id'), table_name='commission_payments')
    op.drop_table('commission_payments')
