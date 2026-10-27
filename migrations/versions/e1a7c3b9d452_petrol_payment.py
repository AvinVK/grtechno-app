"""petrol payment (kohal, 2026-10-27: "we need option of petrol payment... toggle in emp management form...
at checkin time submit odometer pic and its reading... at checkout... approved by admin or project
manager... next day, you can delete that pic... petrol amount = diff in kilometer *4") - one new column on
workers (default off, so nobody changes) and one new table, petrol_entries, one row per check-in/out
session. Adds only; nothing existing is touched or rewritten.

Revision ID: e1a7c3b9d452
Revises: d9b3a6c1e247
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1a7c3b9d452'
down_revision = 'd9b3a6c1e247'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workers', sa.Column('petrol_enabled', sa.Boolean(), nullable=False, server_default='0'))
    op.create_table(
        'petrol_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attendance_id', sa.Integer(), nullable=False),
        sa.Column('user_code', sa.String(length=4), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('in_reading', sa.Integer(), nullable=False),
        sa.Column('in_photo', sa.String(length=80), nullable=True),
        sa.Column('out_reading', sa.Integer(), nullable=True),
        sa.Column('out_photo', sa.String(length=80), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='pending'),
        sa.Column('approved_by_code', sa.String(length=4), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['attendance_id'], ['attendance.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_code'], ['users.code'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approved_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attendance_id', name='uq_petrol_entries_attendance'),
    )
    op.create_index('ix_petrol_entries_user_code', 'petrol_entries', ['user_code'])
    op.create_index('ix_petrol_entries_work_date', 'petrol_entries', ['work_date'])


def downgrade():
    op.drop_index('ix_petrol_entries_work_date', table_name='petrol_entries')
    op.drop_index('ix_petrol_entries_user_code', table_name='petrol_entries')
    op.drop_table('petrol_entries')
    op.drop_column('workers', 'petrol_enabled')
