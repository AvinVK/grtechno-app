"""Client role, and which customer a client-role login belongs to

Revision ID: e5a9c3f7b162
Revises: b8f3a1d6c925
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5a9c3f7b162'
down_revision = 'b8f3a1d6c925'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # No role_modules row for it - a copy of app/reference_data.py's own comment: this role never opens
    # any of the normal Services tiles, its whole experience is the dedicated client portal, gated on
    # role_key alone, not the Module system.
    exists = conn.execute(sa.text("SELECT 1 FROM roles WHERE key = 'client'")).first()
    if not exists:
        op.execute("INSERT INTO roles (key, name, sees_all) VALUES ('client', 'Client', 0)")

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_users_client_id_clients', 'clients', ['client_id'], ['id'], ondelete='SET NULL')
        batch_op.create_index('ix_users_client_id', ['client_id'])


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('ix_users_client_id')
        batch_op.drop_constraint('fk_users_client_id_clients', type_='foreignkey')
        batch_op.drop_column('client_id')
    op.execute("DELETE FROM users WHERE role_key = 'client'")
    op.execute("DELETE FROM roles WHERE key = 'client'")
