"""worker_attendance: status (present/absent, so a colleague's "on leave" report can be recorded even with
no check-in), and project_id - a best guess of which project the day's site name matched

Revision ID: f7b3d5e2a084
Revises: e4f8a2c6d913
Create Date: 2026-09-24 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f7b3d5e2a084'
down_revision = 'e4f8a2c6d913'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('worker_attendance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=10), server_default='present', nullable=False))
        batch_op.add_column(sa.Column('project_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_worker_attendance_project_id_projects', 'projects', ['project_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_worker_attendance_project_id', 'worker_attendance', ['project_id'])


def downgrade():
    op.drop_index('ix_worker_attendance_project_id', table_name='worker_attendance')
    with op.batch_alter_table('worker_attendance', schema=None) as batch_op:
        batch_op.drop_constraint('fk_worker_attendance_project_id_projects', type_='foreignkey')
        batch_op.drop_column('project_id')
        batch_op.drop_column('status')
