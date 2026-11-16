"""The planner's categories (kohal, 2026-11-16) - a kind on each meeting (client meeting / call to make) and each task (site visit / work to do).
Two new columns with defaults; nothing existing is changed.

Revision ID: e5f8c2a14b71
Revises: d4e7b1c93a60
Create Date: 2026-11-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f8c2a14b71'
down_revision = 'd4e7b1c93a60'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('planner_meetings', sa.Column('kind', sa.String(length=20), nullable=False, server_default='client_meeting'))
    op.add_column('planner_tasks', sa.Column('kind', sa.String(length=20), nullable=False, server_default='site_visit'))


def downgrade():
    op.drop_column('planner_tasks', 'kind')
    op.drop_column('planner_meetings', 'kind')
