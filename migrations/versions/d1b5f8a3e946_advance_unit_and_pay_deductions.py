"""Fortnight advances and pay deductions (kohal, 2026-11-09). A daily-wage advance is taken back per 2-week pay period instead of per
month, and the admin can put a deduction against anyone's pay. One new column (every advance already given stays "month") and one
brand-new table; nothing existing is changed.

Revision ID: d1b5f8a3e946
Revises: c9a4e7b3d825
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1b5f8a3e946'
down_revision = 'c9a4e7b3d825'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('salary_advances', sa.Column('unit', sa.String(length=10), nullable=False, server_default='month'))
    op.create_table(
        'pay_deductions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pay_deductions_worker_id'), 'pay_deductions', ['worker_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_pay_deductions_worker_id'), table_name='pay_deductions')
    op.drop_table('pay_deductions')
    op.drop_column('salary_advances', 'unit')
