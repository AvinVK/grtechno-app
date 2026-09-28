"""attendance.work_kind: "marketing" for a check-in to marketing work rather than a project or the office

Revision ID: c7f3a9e2d514
Revises: b6e2d9f4a171
Create Date: 2026-09-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c7f3a9e2d514'
down_revision = 'b6e2d9f4a171'
branch_labels = None
depends_on = None


def upgrade():
    # Empty for every existing row: those were a project, or office work when there's no project.
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('work_kind', sa.String(length=20), nullable=False, server_default=''))


def downgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_column('work_kind')
