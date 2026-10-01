"""mode of payment, date paid and comments on a lead's advance and on each project payment step

Revision ID: b9c253a2584b
Revises: d9b4e6f2a831
Create Date: 2026-10-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b9c253a2584b'
down_revision = 'd9b4e6f2a831'
branch_labels = None
depends_on = None

LEAD_COLUMNS = [
    ('advance_mode', sa.String(length=40), ''),
    ('advance_comments', sa.Text(), ''),
]
PAYMENT_COLUMNS = [
    ('mode', sa.String(length=40), ''),
    ('paid_date', sa.Date(), None),
    ('comments', sa.Text(), ''),
]


def _columns(conn, table):
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def _add_missing(table, columns):
    conn = op.get_bind()
    existing = _columns(conn, table)
    missing = [(name, col_type, default) for name, col_type, default in columns if name not in existing]
    if not missing:
        return
    with op.batch_alter_table(table, schema=None) as batch_op:
        for name, col_type, default in missing:
            if default is None:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))
            else:
                batch_op.add_column(sa.Column(name, col_type, server_default=default, nullable=False))


def upgrade():
    # Defensive: safe to re-run from a partial state (an interrupted earlier attempt), same as every
    # migration since the _alembic_tmp_leads incident - see d9b4e6f2a831.
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_leads"))
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_project_payments"))
    _add_missing('leads', LEAD_COLUMNS)
    _add_missing('project_payments', PAYMENT_COLUMNS)


def downgrade():
    with op.batch_alter_table('project_payments', schema=None) as batch_op:
        batch_op.drop_column('comments')
        batch_op.drop_column('paid_date')
        batch_op.drop_column('mode')
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_column('advance_comments')
        batch_op.drop_column('advance_mode')
