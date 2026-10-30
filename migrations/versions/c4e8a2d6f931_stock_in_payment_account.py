"""stock-in payment account (kohal, 2026-10-31: "even in inventory, if its cash selected then show the bank options")
- one new column on material_movements: which account a cash purchase was paid from. Every existing entry starts
empty. Adds a column only; nothing is rewritten.

Revision ID: c4e8a2d6f931
Revises: b3d7f1a9c524
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e8a2d6f931'
down_revision = 'b3d7f1a9c524'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('material_movements', sa.Column('payment_account', sa.String(length=30), nullable=False, server_default=''))


def downgrade():
    op.drop_column('material_movements', 'payment_account')
