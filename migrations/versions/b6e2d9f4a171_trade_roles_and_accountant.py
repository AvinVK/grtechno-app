"""roles: Welder, Fitter, Helper and Alarm technician (Attendance only), and Accounts renamed Accountant

Revision ID: b6e2d9f4a171
Revises: a3c7e1f5b928
Create Date: 2026-09-28 00:00:00.000000

"""
from alembic import op


revision = 'b6e2d9f4a171'
down_revision = 'a3c7e1f5b928'
branch_labels = None
depends_on = None

# A copy, not an import of app code (a migration must not change when the app does); tests/test_reference_data.py
# checks it matches app/reference_data.py.
TRADE_ROLES = [
    ("welder", "Welder"),
    ("fitter", "Fitter"),
    ("helper", "Helper"),
    ("alarm_technician", "Alarm technician"),
]


def upgrade():
    op.execute("UPDATE roles SET name = 'Accountant' WHERE key = 'accounts'")
    for key, name in TRADE_ROLES:
        op.execute(f"INSERT INTO roles (key, name, sees_all) VALUES ('{key}', '{name}', 0)")
        op.execute(f"INSERT INTO role_modules (role_key, module_key) VALUES ('{key}', 'attendance')")


def downgrade():
    for key, _ in TRADE_ROLES:
        op.execute(f"UPDATE users SET role_key = 'supervisor' WHERE role_key = '{key}'")
        op.execute(f"DELETE FROM role_modules WHERE role_key = '{key}'")
        op.execute(f"DELETE FROM roles WHERE key = '{key}'")
    op.execute("UPDATE roles SET name = 'Accounts' WHERE key = 'accounts'")
