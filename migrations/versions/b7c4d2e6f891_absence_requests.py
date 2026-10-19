"""absence_requests table (kohal, 2026-10-19: "For absent provide option within check in tab ... Absent
should be inform 1 day before") - a daily-wage worker telling the office they won't be in on a future day,
waiting for the admin or a project manager to see and acknowledge it. Never becomes an Attendance row.

Revision ID: b7c4d2e6f891
Revises: a3c7e1f9d548
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c4d2e6f891'
down_revision = 'a3c7e1f9d548'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'absence_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_code', sa.String(length=4), nullable=False),
        sa.Column('for_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(length=200), server_default='', nullable=False),
        sa.Column('status', sa.String(length=10), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('decided_by_code', sa.String(length=4), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_code'], ['users.code'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_code', 'for_date', name='uq_absence_requests_user_date'),
    )
    with op.batch_alter_table('absence_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_absence_requests_user_code'), ['user_code'], unique=False)
        batch_op.create_index(batch_op.f('ix_absence_requests_for_date'), ['for_date'], unique=False)


def downgrade():
    with op.batch_alter_table('absence_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_absence_requests_for_date'))
        batch_op.drop_index(batch_op.f('ix_absence_requests_user_code'))
    op.drop_table('absence_requests')
