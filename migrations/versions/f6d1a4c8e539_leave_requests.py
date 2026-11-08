"""Leave requests (kohal, 2026-11-08) - sick and casual leave for salaried employees, asked for from Attendance and approved by
the admin. A brand-new table only; nothing existing is changed.

Revision ID: f6d1a4c8e539
Revises: e5c9d3f7b428
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6d1a4c8e539'
down_revision = 'e5c9d3f7b428'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'leave_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('days', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='pending'),
        sa.Column('deducted_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('extra_paid_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unpaid_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('decision_note', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('requested_by_code', sa.String(length=4), nullable=True),
        sa.Column('decided_by_code', sa.String(length=4), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['decided_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_leave_requests_worker_id'), 'leave_requests', ['worker_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_leave_requests_worker_id'), table_name='leave_requests')
    op.drop_table('leave_requests')
