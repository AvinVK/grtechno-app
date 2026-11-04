"""Admin purchases (kohal, 2026-11-04) - what the admin buys directly, paid from one of their own accounts, without
allotting cash to anyone. A brand new table; nothing existing changes.

Revision ID: d2f8c4b6e013
Revises: c1e7b3a5d902
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'd2f8c4b6e013'
down_revision = 'c1e7b3a5d902'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_purchases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=10), nullable=False, server_default='other'),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('material_name', sa.String(length=120), nullable=False),
        sa.Column('quantity', sa.Numeric(12, 2), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('gst_percent', sa.Numeric(5, 2), nullable=False, server_default='0'),
        sa.Column('gst_amount', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('supplier', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('note', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('payment_account', sa.String(length=40), nullable=False),
        sa.Column('bill_filename', sa.String(length=80), nullable=True),
        sa.Column('movement_id', sa.Integer(), nullable=True),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('admin_purchases')
