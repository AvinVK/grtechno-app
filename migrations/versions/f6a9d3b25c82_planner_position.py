"""The planner's drag-to-order (kohal, 2026-11-16) - a position on each meeting and task, so a day's tiles keep the order the admin dragged them into.
Two new columns with a default; nothing existing is changed.

Revision ID: f6a9d3b25c82
Revises: e5f8c2a14b71
Create Date: 2026-11-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a9d3b25c82'
down_revision = 'e5f8c2a14b71'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('planner_meetings', sa.Column('position', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('planner_tasks', sa.Column('position', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('planner_tasks', 'position')
    op.drop_column('planner_meetings', 'position')
