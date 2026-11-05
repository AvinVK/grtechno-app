"""Supplier details and a starting balance (kohal, 2026-11-05) - who the supplier is (contact person, email, GST number,
address) and what was already owed to them in the ledger kept before this app, carried over as an opening balance.
New columns on suppliers only, all empty or 0 to begin with, so every existing supplier and what it owes stays exactly
as it was.

Revision ID: b7e1f9a3d468
Revises: a6d0e8f4c357
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7e1f9a3d468'
down_revision = 'a6d0e8f4c357'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('suppliers', sa.Column('contact_person', sa.String(length=120), nullable=False, server_default=''))
    op.add_column('suppliers', sa.Column('email', sa.Text(), nullable=True))
    op.add_column('suppliers', sa.Column('gstin', sa.String(length=20), nullable=False, server_default=''))
    op.add_column('suppliers', sa.Column('address', sa.Text(), nullable=True))
    op.add_column('suppliers', sa.Column('opening_balance', sa.Numeric(14, 2), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('suppliers', 'opening_balance')
    op.drop_column('suppliers', 'address')
    op.drop_column('suppliers', 'gstin')
    op.drop_column('suppliers', 'email')
    op.drop_column('suppliers', 'contact_person')
