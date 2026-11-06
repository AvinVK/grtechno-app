"""Salary advances (kohal, 2026-11-06) - money given to an employee ahead of pay, taken back in equal parts across the months that
follow. A brand-new table only; nothing existing is changed.

Revision ID: c8f2a6b4d159
Revises: b7e1f9a3d468
Create Date: 2026-11-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'c8f2a6b4d159'
down_revision = 'b7e1f9a3d468'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'salary_advances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('months', sa.Integer(), nullable=False),
        sa.Column('first_month', sa.Date(), nullable=False),
        sa.Column('given_date', sa.Date(), nullable=False),
        sa.Column('payment_account', sa.String(length=40), nullable=False, server_default=''),
        sa.Column('note', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_salary_advances_worker_id'), 'salary_advances', ['worker_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_salary_advances_worker_id'), table_name='salary_advances')
    op.drop_table('salary_advances')
