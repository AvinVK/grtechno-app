"""Sub-admin role, and the states a sub-admin is scoped to see clients/projects for

Revision ID: 0ba43da7795f
Revises: 5dcbdf70f991
Create Date: 2026-10-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0ba43da7795f'
down_revision = '5dcbdf70f991'
branch_labels = None
depends_on = None

# A copy, not an import of app code (a migration must not change when the app does); tests/test_reference_data.py
# checks it matches app/reference_data.py.
SUB_ADMIN_MODULES = ['clients', 'projects', 'attendance']


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_user_states"))

    exists = conn.execute(sa.text("SELECT 1 FROM roles WHERE key = 'sub_admin'")).first()
    if not exists:
        op.execute("INSERT INTO roles (key, name, sees_all) VALUES ('sub_admin', 'Sub-admin', 0)")
        for module in SUB_ADMIN_MODULES:
            op.execute(f"INSERT INTO role_modules (role_key, module_key) VALUES ('sub_admin', '{module}')")

    if not conn.dialect.has_table(conn, 'user_states'):
        op.create_table(
            'user_states',
            sa.Column('user_code', sa.String(length=4), nullable=False),
            sa.Column('state', sa.String(length=80), nullable=False),
            sa.ForeignKeyConstraint(['user_code'], ['users.code'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('user_code', 'state'),
        )


def downgrade():
    op.drop_table('user_states')
    op.execute("UPDATE users SET role_key = 'sales_field' WHERE role_key = 'sub_admin'")
    op.execute("DELETE FROM role_modules WHERE role_key = 'sub_admin'")
    op.execute("DELETE FROM roles WHERE key = 'sub_admin'")
