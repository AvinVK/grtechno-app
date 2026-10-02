"""site name on a survey - what tells one client's site apart from another

Revision ID: 30f0f4d3a002
Revises: 0ba43da7795f
Create Date: 2026-10-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '30f0f4d3a002'
down_revision = '0ba43da7795f'
branch_labels = None
depends_on = None


def _columns(conn, table):
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_lead_surveys"))
    if 'site_name' not in _columns(conn, 'lead_surveys'):
        with op.batch_alter_table('lead_surveys', schema=None) as batch_op:
            batch_op.add_column(sa.Column('site_name', sa.String(length=160), server_default='', nullable=False))


def downgrade():
    with op.batch_alter_table('lead_surveys', schema=None) as batch_op:
        batch_op.drop_column('site_name')
