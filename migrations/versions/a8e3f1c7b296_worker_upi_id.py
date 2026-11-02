"""An optional UPI ID per employee (kohal, 2026-11-02) - lets "Pay with PhonePe" open the app already filled in for them.
One new nullable column on workers; nothing existing changes.

Revision ID: a8e3f1c7b296
Revises: f7c1d5a9e264
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'a8e3f1c7b296'
down_revision = 'f7c1d5a9e264'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workers', sa.Column('upi_id', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('workers', 'upi_id')
