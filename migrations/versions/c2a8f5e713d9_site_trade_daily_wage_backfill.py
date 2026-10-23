"""Backfill employment_type/fooding_opt_in for existing site-trade workers (kohal, 2026-10-23: "why cant he
see fooding and workplan and his attendance history... whatever things he shuld be able to see as daily
wages") - welder/fitter/helper/alarm_technician are day labour (reference_data.py: "they sign in only to
check themselves in and out"), so this matches the new default in auth.sync_worker_for_user going forward
and catches everyone whose account already existed before that change. Only touches a worker whose
employment_type was never set at all, so an admin's own deliberate choice (e.g. "regular") is left alone.

One-way, same reasoning as a3c7e1f9d548: no record of which rows this touches, so downgrade doesn't
attempt to undo it.

Revision ID: c2a8f5e713d9
Revises: b6e4d928a3f7
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'c2a8f5e713d9'
down_revision = 'b6e4d928a3f7'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE workers
        SET employment_type = 'daily_wages', fooding_opt_in = 1
        WHERE employment_type = ''
          AND user_code IN (
              SELECT code FROM users WHERE role_key IN ('welder', 'fitter', 'helper', 'alarm_technician')
          )
    """))


def downgrade():
    pass
