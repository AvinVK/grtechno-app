"""A category on every cash purchase - material or other expenses (kohal, 2026-11-04). An approved material
purchase is stocked into Inventory automatically; movement_id remembers which stock-in it became so approval can
never stock it twice. Two new columns on cash_purchases; older rows are simply "other" and nothing existing changes.

Revision ID: b9d4a2e6c371
Revises: a8e3f1c7b296
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'b9d4a2e6c371'
down_revision = 'a8e3f1c7b296'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cash_purchases', sa.Column('category', sa.String(length=10), nullable=False, server_default='other'))
    op.add_column('cash_purchases', sa.Column('movement_id', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('cash_purchases', 'movement_id')
    op.drop_column('cash_purchases', 'category')
