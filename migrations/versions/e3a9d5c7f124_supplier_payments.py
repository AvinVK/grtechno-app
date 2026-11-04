"""Paying a supplier (kohal, 2026-11-04) - a contact number and UPI ID on each supplier, and a table of the payments
made against what is owed on credit. Two new nullable columns on suppliers and one brand-new table; nothing existing
changes.

Revision ID: e3a9d5c7f124
Revises: d2f8c4b6e013
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'e3a9d5c7f124'
down_revision = 'd2f8c4b6e013'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('suppliers', sa.Column('phone', sa.Text(), nullable=True))
    op.add_column('suppliers', sa.Column('upi_id', sa.Text(), nullable=True))
    op.create_table(
        'supplier_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('supplier_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('payment_account', sa.String(length=40), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_supplier_payments_supplier_id', 'supplier_payments', ['supplier_id'])


def downgrade():
    op.drop_index('ix_supplier_payments_supplier_id', table_name='supplier_payments')
    op.drop_table('supplier_payments')
    op.drop_column('suppliers', 'upi_id')
    op.drop_column('suppliers', 'phone')
