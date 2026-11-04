"""Project managers can open Inventory (kohal, 2026-11-04) - one added row in role_modules for the Project manager role,
only if it is not there already. Nothing is removed or changed.

Revision ID: f4b8e6d2a135
Revises: e3a9d5c7f124
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4b8e6d2a135'
down_revision = 'e3a9d5c7f124'
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("""
        INSERT INTO role_modules (role_key, module_key, write_access)
        SELECT r.key, m.key, 1 FROM roles r, modules m
        WHERE r.key = 'project_manager' AND m.key = 'inventory'
          AND NOT EXISTS (SELECT 1 FROM role_modules x WHERE x.role_key = r.key AND x.module_key = m.key)
    """))


def downgrade():
    op.get_bind().execute(sa.text("DELETE FROM role_modules WHERE role_key = 'project_manager' AND module_key = 'inventory'"))
