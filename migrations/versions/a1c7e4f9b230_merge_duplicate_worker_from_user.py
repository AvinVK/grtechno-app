"""Data cleanup, not a schema change: a 'user_account' Worker (see auth.sync_worker_for_user) created
before it knew to check for an already-existing, same-named Worker first - e.g. someone already tracked
from the WhatsApp attendance import, later also given a login - duplicated that person instead of linking
to them. For each such pair, point the original (older, already has whatever attendance history) at the
User instead, and remove the duplicate.

Revision ID: a1c7e4f9b230
Revises: f3d81a6c5e92
Create Date: 2026-10-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c7e4f9b230'
down_revision = 'f3d81a6c5e92'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        CREATE TEMP TABLE dupe_links AS
        SELECT d.id AS dupe_id, d.user_code AS user_code,
               (SELECT w.id FROM workers w
                WHERE w.user_code IS NULL AND w.id != d.id AND lower(w.name) = lower(d.name)
                ORDER BY w.id LIMIT 1) AS original_id
        FROM workers d
        WHERE d.source = 'user_account'
    """))
    conn.execute(sa.text("DELETE FROM dupe_links WHERE original_id IS NULL"))
    # The duplicate goes first - it's still holding the user_code the original is about to take, and
    # workers.user_code is unique, so both can't have it at once even for a moment.
    conn.execute(sa.text("DELETE FROM workers WHERE id IN (SELECT dupe_id FROM dupe_links)"))
    conn.execute(sa.text("""
        UPDATE workers SET user_code = (SELECT user_code FROM dupe_links WHERE original_id = workers.id)
        WHERE id IN (SELECT original_id FROM dupe_links)
    """))
    conn.execute(sa.text("DROP TABLE dupe_links"))
    # Belt and braces: every linked Worker's role should match its User's current role, in case any drifted.
    conn.execute(sa.text("""
        UPDATE workers SET role_key = (SELECT u.role_key FROM users u WHERE u.code = workers.user_code)
        WHERE user_code IS NOT NULL
    """))


def downgrade():
    """Nothing to undo - which original row absorbed which duplicate isn't kept anywhere once this runs."""
