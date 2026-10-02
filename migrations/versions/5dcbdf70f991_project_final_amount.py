"""a project's final amount, set from the closing measurement

Revision ID: 5dcbdf70f991
Revises: b9c253a2584b
Create Date: 2026-10-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '5dcbdf70f991'
down_revision = 'b9c253a2584b'
branch_labels = None
depends_on = None


def _columns(conn, table):
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_projects"))
    if 'final_amount' not in _columns(conn, 'projects'):
        with op.batch_alter_table('projects', schema=None) as batch_op:
            batch_op.add_column(sa.Column('final_amount', sa.Numeric(14, 2), nullable=True))


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('final_amount')
