"""House rent / petrol allowance on an employee (kohal, 2026-11-08) - a fixed monthly amount added on top of a salary, as on the
monthly payment sheet. One new, empty (nullable) column; nothing existing is changed.

Revision ID: e5c9d3f7b428
Revises: d4b8c2e6a317
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5c9d3f7b428'
down_revision = 'd4b8c2e6a317'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workers', sa.Column('allowance_amount', sa.Numeric(14, 2), nullable=True))


def downgrade():
    op.drop_column('workers', 'allowance_amount')
