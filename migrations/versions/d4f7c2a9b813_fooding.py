"""fooding_accounts table (kohal, 2026-10-18): a daily-wage worker's food allowance - the admin or
accountant allots money, and Rs 200/day comes off it automatically (no cron - see FoodingAccount's own
docstring) until it's paused for that one person.

Revision ID: d4f7c2a9b813
Revises: c8e3b1f6a729
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4f7c2a9b813'
down_revision = 'c8e3b1f6a729'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fooding_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('allotted_total', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('deducted_total', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('anchor_date', sa.Date(), nullable=False),
        sa.Column('is_paused', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('worker_id'),
    )


def downgrade():
    op.drop_table('fooding_accounts')
