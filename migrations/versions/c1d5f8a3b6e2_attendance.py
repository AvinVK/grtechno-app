"""attendance: self check-in / check-out, one row per person per day

Revision ID: c1d5f8a3b6e2
Revises: b7c2e4a91d05
Create Date: 2026-09-23 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c1d5f8a3b6e2'
down_revision = 'b7c2e4a91d05'
branch_labels = None
depends_on = None

# Copied from app/reference_data.py on purpose: a migration must not depend on app code.
ATTENDANCE_MODULE = {
    'key': 'attendance', 'name': 'Attendance', 'icon': 'attendance', 'path': '/attendance',
    'sort_order': 4, 'is_active': True, 'admin_only': False,
}
ROLES_GETTING_ATTENDANCE = ['sales_field', 'sales_office', 'project_manager', 'supervisor', 'accounts']


def upgrade():
    modules = sa.table('modules', sa.column('key'), sa.column('name'), sa.column('icon'), sa.column('path'),
                        sa.column('sort_order'), sa.column('is_active'), sa.column('admin_only'))
    op.bulk_insert(modules, [ATTENDANCE_MODULE])

    role_modules = sa.table('role_modules', sa.column('role_key'), sa.column('module_key'))
    op.bulk_insert(role_modules, [{'role_key': r, 'module_key': 'attendance'} for r in ROLES_GETTING_ATTENDANCE])

    op.create_table(
        'attendance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_code', sa.String(length=4), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('check_in_at', sa.DateTime(), nullable=False),
        sa.Column('check_out_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.String(length=400), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_code'], ['users.code'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_code', 'work_date', name='uq_attendance_user_date'),
    )
    op.create_index('ix_attendance_user_code', 'attendance', ['user_code'])
    op.create_index('ix_attendance_work_date', 'attendance', ['work_date'])
    op.create_index('ix_attendance_project_id', 'attendance', ['project_id'])


def downgrade():
    op.drop_table('attendance')
    op.get_bind().execute(sa.text(
        "DELETE FROM role_modules WHERE module_key = 'attendance'"))
    op.get_bind().execute(sa.text("DELETE FROM modules WHERE key = 'attendance'"))
