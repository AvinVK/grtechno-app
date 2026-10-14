"""Data cleanup, not a schema change: drop every employee added through the old "Add employee" form (now
removed - see app/workers.py), and backfill a matching Worker for any active User from Users & roles that's
missing one - e.g. one activated between the previous migration's backfill (e7a4c9f2b816, which didn't
check active status yet) and the "only once active" rule landing (see app/auth.py sync_worker_for_user).

Revision ID: f3d81a6c5e92
Revises: e7a4c9f2b816
Create Date: 2026-10-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f3d81a6c5e92'
down_revision = 'e7a4c9f2b816'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM workers WHERE source = 'manual'"))
    conn.execute(sa.text("""
        INSERT INTO workers (name, category, role_key, source, user_code, created_at)
        SELECT u.name, 'staff', u.role_key, 'user_account', u.code, CURRENT_TIMESTAMP
        FROM users u
        WHERE u.is_admin = 0
          AND u.password_hash IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM workers w WHERE w.user_code = u.code)
    """))


def downgrade():
    """Nothing to undo - the manually-added employees this deleted are gone for good, and there's no way
    to tell which of the backfilled rows downgrading should remove again without also removing ones that
    were already there before this ran."""
