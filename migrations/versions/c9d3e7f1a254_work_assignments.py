"""Work plan module + work_assignments table (kohal, 2026-10-19: "Next day work scheduling by project
manager or by accountant or admin ... This allotment should approved by Admin") - a project manager or the
accountant drafts a worker's next day's work (against a project, or a location for office staff), and it
waits for the admin specifically to approve before it shows up on the assigned worker's own Me hub.

Revision ID: c9d3e7f1a254
Revises: b7c4d2e6f891
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d3e7f1a254'
down_revision = 'b7c4d2e6f891'
branch_labels = None
depends_on = None

# Copied from app/reference_data.py on purpose: a migration must not depend on app code.
WORKPLAN_MODULE = {
    'key': 'workplan', 'name': 'Work plan', 'icon': 'schedule', 'path': '/workplan',
    'sort_order': 6, 'is_active': True, 'admin_only': False,
}
ROLES_GETTING_WORKPLAN = ['project_manager', 'accounts']


def upgrade():
    modules = sa.table('modules', sa.column('key'), sa.column('name'), sa.column('icon'), sa.column('path'),
                        sa.column('sort_order'), sa.column('is_active'), sa.column('admin_only'))
    op.bulk_insert(modules, [WORKPLAN_MODULE])

    role_modules = sa.table('role_modules', sa.column('role_key'), sa.column('module_key'))
    op.bulk_insert(role_modules, [{'role_key': r, 'module_key': 'workplan'} for r in ROLES_GETTING_WORKPLAN])

    op.create_table(
        'work_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('for_date', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('location', sa.String(length=120), server_default='', nullable=False),
        sa.Column('task', sa.String(length=300), server_default='', nullable=False),
        sa.Column('status', sa.String(length=10), server_default='pending', nullable=False),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('approved_by_code', sa.String(length=4), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approved_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('work_assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_work_assignments_for_date'), ['for_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_work_assignments_worker_id'), ['worker_id'], unique=False)


def downgrade():
    with op.batch_alter_table('work_assignments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_work_assignments_worker_id'))
        batch_op.drop_index(batch_op.f('ix_work_assignments_for_date'))
    op.drop_table('work_assignments')
    op.get_bind().execute(sa.text("DELETE FROM role_modules WHERE module_key = 'workplan'"))
    op.get_bind().execute(sa.text("DELETE FROM modules WHERE key = 'workplan'"))
