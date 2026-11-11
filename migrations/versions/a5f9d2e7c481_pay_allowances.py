"""Pay allowances (kohal, 2026-11-11) - an amount, with a note saying which allowance it is, the admin adds to one period of someone's pay.
One brand-new table only; nothing existing is changed.

Revision ID: a5f9d2e7c481
Revises: f3d7b0c5a268
Create Date: 2026-11-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'a5f9d2e7c481'
down_revision = 'f3d7b0c5a268'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pay_allowances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('note', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pay_allowances_worker_id'), 'pay_allowances', ['worker_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_pay_allowances_worker_id'), table_name='pay_allowances')
    op.drop_table('pay_allowances')
