"""Workers get a role, same list as Users & roles - replaces the manpower/staff split

Revision ID: a3c7f1e9b204
Revises: 0a713797f60c
Create Date: 2026-10-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3c7f1e9b204'
down_revision = '0a713797f60c'
branch_labels = None
depends_on = None


def _columns(conn, table):
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_workers"))
    if 'role_key' not in _columns(conn, 'workers'):
        with op.batch_alter_table('workers', schema=None) as batch_op:
            batch_op.add_column(sa.Column('role_key', sa.String(length=30), nullable=True))
            batch_op.create_foreign_key('fk_workers_role_key_roles', 'roles', ['role_key'], ['key'])
    # Existing workers (all imported from WhatsApp, with no role information) start unassigned - the
    # admin assigns a role per person from Employee management, same as the old category was never set
    # automatically either.


def downgrade():
    with op.batch_alter_table('workers', schema=None) as batch_op:
        batch_op.drop_constraint('fk_workers_role_key_roles', type_='foreignkey')
        batch_op.drop_column('role_key')
