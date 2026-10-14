"""Full role-based access rollout (kohal's access matrix, 2026-10-14): a write_access flag per (role,
module) grant so a role can look without being able to touch anything (Accountant, Office Assistant on
Users & roles / Employee management); two new permission-only modules for those two pages (not shown as
tiles - see Module.in_nav); Inventory is no longer admin-only, now that roles are defined for it; and the
four roles already added on the fly in prod (Office Assistant, Alarm Tech cum site supervisor, Company
Director, Office Assistant cum client consultant) get real role_modules grants, linked by name since prod's
copies of them already exist under whatever key roles.py's auto-slug gave them at the time, not necessarily
the ones below.

A copy, not an import of app code (a migration must not change when the app does); tests/test_reference_data.py
checks it matches app/reference_data.py.

Revision ID: c3f6b1d8e4a7
Revises: b9d4c2a71e03
Create Date: 2026-10-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3f6b1d8e4a7'
down_revision = 'b9d4c2a71e03'
branch_labels = None
depends_on = None

# key, name, sees_all - only the four prod already grew on the fly; the ten already seeded are untouched.
NEW_ROLES = [
    ("office_assistant", "Office Assistant", True),
    ("alarm_tech_cum_site_supervisor", "Alarm Tech cum site supervisor", False),
    ("company_director", "Company Director", True),
    ("office_assistant_consultant", "Office Assistant cum client consultant", True),
]

# Every role's full, final module list - replaces whatever that role had before, not added to it.
# Matched by role NAME (see module docstring), not key.
ROLE_MODULES_BY_NAME = {
    "Sales (field)": ["leads", "attendance"],
    "Sales (office)": ["leads", "attendance"],
    "Project manager": ["projects", "attendance"],
    "Site supervisor": ["projects", "attendance"],
    "Accountant": ["clients", "projects", "inventory", "users", "workforce", "attendance"],
    "Sub-admin": ["clients", "projects", "attendance"],
    "Welder": ["attendance"],
    "Fitter": ["attendance"],
    "Helper": ["attendance"],
    "Alarm technician": ["attendance"],
    "Office Assistant": ["clients", "projects", "inventory", "users", "workforce", "attendance"],
    "Alarm Tech cum site supervisor": ["projects", "attendance"],
    "Company Director": ["clients", "projects", "inventory", "users", "workforce", "attendance", "leads"],
    "Office Assistant cum client consultant": ["clients", "projects", "inventory", "users", "workforce", "attendance", "leads"],
}

# (role name, module) that can look but not touch - everything else granted above is full access.
READONLY_BY_NAME = {
    ("Accountant", "users"), ("Accountant", "workforce"),
    ("Office Assistant", "users"), ("Office Assistant", "workforce"),
}


def upgrade():
    conn = op.get_bind()

    with op.batch_alter_table('role_modules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('write_access', sa.Boolean(), server_default='1', nullable=False))
    with op.batch_alter_table('modules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('in_nav', sa.Boolean(), server_default='1', nullable=False))

    conn.execute(sa.text("""
        INSERT INTO modules (key, name, icon, path, sort_order, is_active, admin_only, in_nav)
        SELECT 'users', 'Users & roles', 'user', '/users', 90, 1, 0, 0
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE key = 'users')
    """))
    conn.execute(sa.text("""
        INSERT INTO modules (key, name, icon, path, sort_order, is_active, admin_only, in_nav)
        SELECT 'workforce', 'Employee management', 'manpower', '/workforce', 91, 1, 0, 0
        WHERE NOT EXISTS (SELECT 1 FROM modules WHERE key = 'workforce')
    """))
    conn.execute(sa.text("UPDATE modules SET admin_only = 0 WHERE key = 'inventory'"))

    for key, name, sees_all in NEW_ROLES:
        conn.execute(sa.text("""
            INSERT INTO roles (key, name, sees_all)
            SELECT :key, :name, :sees_all
            WHERE NOT EXISTS (SELECT 1 FROM roles WHERE key = :key)
              AND NOT EXISTS (SELECT 1 FROM roles WHERE name = :name)
        """), {"key": key, "name": name, "sees_all": int(sees_all)})

    for name, modules in ROLE_MODULES_BY_NAME.items():
        conn.execute(sa.text("""
            DELETE FROM role_modules WHERE role_key = (SELECT key FROM roles WHERE name = :name)
        """), {"name": name})
        for module_key in modules:
            write_access = 0 if (name, module_key) in READONLY_BY_NAME else 1
            conn.execute(sa.text("""
                INSERT INTO role_modules (role_key, module_key, write_access)
                SELECT r.key, :module_key, :write_access FROM roles r WHERE r.name = :name
            """), {"name": name, "module_key": module_key, "write_access": write_access})


def downgrade():
    """Only the schema and the two new standalone modules reverse cleanly - which role_modules rows existed
    before this ran (and under what write_access) isn't kept anywhere, so that reset can't be undone; the
    four roles this found or added in prod are left in place too, since other data may already reference
    them by the time anyone downgrades."""
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM role_modules WHERE module_key IN ('users', 'workforce')"))
    conn.execute(sa.text("DELETE FROM modules WHERE key IN ('users', 'workforce')"))
    conn.execute(sa.text("UPDATE modules SET admin_only = 1 WHERE key = 'inventory'"))
    with op.batch_alter_table('modules', schema=None) as batch_op:
        batch_op.drop_column('in_nav')
    with op.batch_alter_table('role_modules', schema=None) as batch_op:
        batch_op.drop_column('write_access')
