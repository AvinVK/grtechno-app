"""Petrol cash that accumulates (kohal, 2026-11-04) - the employee raises one request for any part of what petrol they
are owed, the admin pays an amount (and says from which account), and what is paid settles against the balance. A
brand new table; every existing petrol entry and its per-day cash status is left exactly as it was.

Revision ID: a6d0e8f4c357
Revises: f4b8e6d2a135
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'a6d0e8f4c357'
down_revision = 'f4b8e6d2a135'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'petrol_payouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_code', sa.String(length=4), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('amount_paid', sa.Numeric(14, 2), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='requested'),
        sa.Column('payment_account', sa.String(length=40), nullable=False, server_default=''),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('decided_by_code', sa.String(length=4), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_code'], ['users.code'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_petrol_payouts_user_code', 'petrol_payouts', ['user_code'])


def downgrade():
    op.drop_index('ix_petrol_payouts_user_code', table_name='petrol_payouts')
    op.drop_table('petrol_payouts')
