"""site name on a project - the same one the lead's survey captured

Revision ID: 6d5c22cb4c46
Revises: 30f0f4d3a002
Create Date: 2026-10-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '6d5c22cb4c46'
down_revision = '30f0f4d3a002'
branch_labels = None
depends_on = None


def _columns(conn, table):
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_projects"))
    if 'site_name' not in _columns(conn, 'projects'):
        with op.batch_alter_table('projects', schema=None) as batch_op:
            batch_op.add_column(sa.Column('site_name', sa.String(length=160), server_default='', nullable=False))


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('site_name')
