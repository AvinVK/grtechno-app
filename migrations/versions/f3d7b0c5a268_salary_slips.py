"""Salary slips (kohal, 2026-11-10) - the payment sheet row the admin releases to an employee, kept as it was when released. One brand-new
table only; nothing existing is changed.

Revision ID: f3d7b0c5a268
Revises: e2c6a9b4f157
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3d7b0c5a268'
down_revision = 'e2c6a9b4f157'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'salary_slips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('label', sa.String(length=40), nullable=False, server_default=''),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('released_at', sa.DateTime(), nullable=False),
        sa.Column('released_by_code', sa.String(length=4), nullable=True),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['released_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('worker_id', 'kind', 'period_start', name='uq_salary_slip_period'),
    )
    op.create_index(op.f('ix_salary_slips_worker_id'), 'salary_slips', ['worker_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_salary_slips_worker_id'), table_name='salary_slips')
    op.drop_table('salary_slips')
