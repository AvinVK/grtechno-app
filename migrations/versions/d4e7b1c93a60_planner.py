"""The admin's meeting planner (kohal, 2026-11-16) - two new tables, planner_meetings and planner_tasks. Nothing existing is changed.

Revision ID: d4e7b1c93a60
Revises: c8d2a5f1b407
Create Date: 2026-11-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e7b1c93a60'
down_revision = 'c8d2a5f1b407'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'planner_meetings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('logged_on', sa.Date(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=True),
        sa.Column('client_name', sa.String(length=160), nullable=False),
        sa.Column('address', sa.Text(), nullable=False, server_default=''),
        sa.Column('contact_no', sa.Text(), nullable=False, server_default=''),
        sa.Column('purpose', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('place', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('meeting_date', sa.Date(), nullable=False),
        sa.Column('meeting_time', sa.Time(), nullable=True),
        sa.Column('duration_min', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='planned'),
        sa.Column('remark', sa.Text(), nullable=False, server_default=''),
        sa.Column('next_plan', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('next_date', sa.Date(), nullable=True),
        sa.Column('follow_up_of_id', sa.Integer(), nullable=True),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['follow_up_of_id'], ['planner_meetings.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_planner_meetings_meeting_date', 'planner_meetings', ['meeting_date'])
    op.create_table(
        'planner_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_date', sa.Date(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('task_time', sa.Time(), nullable=True),
        sa.Column('duration_min', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('done', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_planner_tasks_task_date', 'planner_tasks', ['task_date'])


def downgrade():
    op.drop_index('ix_planner_tasks_task_date', table_name='planner_tasks')
    op.drop_table('planner_tasks')
    op.drop_index('ix_planner_meetings_meeting_date', table_name='planner_meetings')
    op.drop_table('planner_meetings')
