"""GST on a cash purchase (kohal, 2026-11-04) - an optional percentage on the employee's purchase; the amount spent
becomes cost plus GST, same as a stock-in. Two new columns on cash_purchases, defaulting to 0, so every existing
row keeps its amount exactly as it was.

Revision ID: c1e7b3a5d902
Revises: b9d4a2e6c371
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1e7b3a5d902'
down_revision = 'b9d4a2e6c371'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cash_purchases', sa.Column('gst_percent', sa.Numeric(5, 2), nullable=False, server_default='0'))
    op.add_column('cash_purchases', sa.Column('gst_amount', sa.Numeric(14, 2), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('cash_purchases', 'gst_amount')
    op.drop_column('cash_purchases', 'gst_percent')
