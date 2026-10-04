"""more services: Fire advisory, Final NOC and Renewal NOC

Revision ID: eff82647a228
Revises: 6d5c22cb4c46
Create Date: 2026-10-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'eff82647a228'
down_revision = '6d5c22cb4c46'
branch_labels = None
depends_on = None

# A copy, not an import of app code; tests/test_reference_data.py checks it matches app/reference_data.py.
ACTIVE_SERVICES = [
    "Sprinklers setup", "Fire alarms", "Hydrant system and pump house", "Supply of extinguishers",
    "Gas suppression", "Electrical panel suppression", "Provisional NOC and compliance",
    "Final NOC and fire audits", "AMC", "Refilling of fire extinguishers",
    "Fire advisory", "Final NOC", "Renewal NOC", "Other",
]
NEW_SERVICES = ["Fire advisory", "Final NOC", "Renewal NOC"]


def upgrade():
    conn = op.get_bind()
    for name in NEW_SERVICES:
        exists = conn.execute(sa.text("SELECT 1 FROM services WHERE name = :n"), {'n': name}).first()
        if not exists:
            op.execute(f"INSERT INTO services (name, sort_order, is_active) VALUES ('{name}', 0, 1)")
    for i, name in enumerate(ACTIVE_SERVICES, start=1):
        conn.execute(sa.text("UPDATE services SET sort_order = :o, is_active = 1 WHERE name = :n"), {'o': i, 'n': name})


def downgrade():
    for name in NEW_SERVICES:
        op.execute(f"DELETE FROM lead_services WHERE service_id IN (SELECT id FROM services WHERE name = '{name}')")
        op.execute(f"DELETE FROM project_services WHERE service_id IN (SELECT id FROM services WHERE name = '{name}')")
        op.execute(f"DELETE FROM services WHERE name = '{name}'")
