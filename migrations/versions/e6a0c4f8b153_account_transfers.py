"""Self transfers between the admin's own accounts (kohal, 2026-11-02) - one new table, nothing existing is touched.

Revision ID: e6a0c4f8b153
Revises: d5f9b3e7a042
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'e6a0c4f8b153'
down_revision = 'd5f9b3e7a042'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'account_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('from_account', sa.String(length=40), nullable=False),
        sa.Column('to_account', sa.String(length=40), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('account_transfers')
