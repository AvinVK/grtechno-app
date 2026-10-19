"""Rename the Work plan module's nav label to match its new Announcements subtab (kohal, 2026-10-19:
"rename work plan to work plan and announcements. both should be a subtabs") - a data-only rename, no
schema change; the module's key/path/icon/sort_order all stay the same.

Revision ID: a8e5d3b7f204
Revises: f3a7c9e2d615
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'a8e5d3b7f204'
down_revision = 'f3a7c9e2d615'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE modules SET name = 'Work plan and announcements' WHERE key = 'workplan'"))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE modules SET name = 'Work plan' WHERE key = 'workplan'"))
