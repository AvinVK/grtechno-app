"""Projects run by another team (kohal, 2026-11-14) - a switch on a project: material requests are off and its Expense tab takes plain
expenses. One new column with a default of off; nothing existing is changed.

Revision ID: c8d2a5f1b407
Revises: b6a0e3d8f592
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'c8d2a5f1b407'
down_revision = 'b6a0e3d8f592'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('projects', sa.Column('managed_by_others', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('projects', 'managed_by_others')
