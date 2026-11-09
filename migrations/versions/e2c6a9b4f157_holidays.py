"""Holidays (kohal, 2026-11-10) - a day the admin declares a paid holiday for every salaried employee and for the daily-wage employees
picked. Two brand-new tables only; nothing existing is changed.

Revision ID: e2c6a9b4f157
Revises: d1b5f8a3e946
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2c6a9b4f157'
down_revision = 'd1b5f8a3e946'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'holidays',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('holiday_date', sa.Date(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_holidays_holiday_date'), 'holidays', ['holiday_date'], unique=False)
    op.create_table(
        'holiday_workers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('holiday_id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['holiday_id'], ['holidays.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_holiday_workers_holiday_id'), 'holiday_workers', ['holiday_id'], unique=False)
    op.create_index(op.f('ix_holiday_workers_worker_id'), 'holiday_workers', ['worker_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_holiday_workers_worker_id'), table_name='holiday_workers')
    op.drop_index(op.f('ix_holiday_workers_holiday_id'), table_name='holiday_workers')
    op.drop_table('holiday_workers')
    op.drop_index(op.f('ix_holidays_holiday_date'), table_name='holidays')
    op.drop_table('holidays')
