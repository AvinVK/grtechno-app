"""Expense type on an "Other expenses" purchase (kohal, 2026-11-09) - office, Dhanbad office, travelling, fooding... One new, empty
column on the admin purchases table; nothing existing is changed.

Revision ID: c9a4e7b3d825
Revises: b8f3d6a2c714
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9a4e7b3d825'
down_revision = 'b8f3d6a2c714'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('admin_purchases', sa.Column('expense_head', sa.String(length=60), nullable=False, server_default=''))


def downgrade():
    op.drop_column('admin_purchases', 'expense_head')
