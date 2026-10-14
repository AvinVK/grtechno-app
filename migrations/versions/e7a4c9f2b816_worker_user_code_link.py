"""Link a Worker to the User it stands in for - every non-admin User now gets a matching Worker row made
automatically (see app/auth.py sync_worker_for_user), so they show up wherever Workers do (Enquired by,
surveyor...) without being added twice. Backfills one for every existing non-admin User who doesn't
already have one.

Revision ID: e7a4c9f2b816
Revises: b2c5f7a913de
Create Date: 2026-10-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7a4c9f2b816'
down_revision = 'b2c5f7a913de'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_code', sa.String(length=4), nullable=True))
        batch_op.create_index(batch_op.f('ix_workers_user_code'), ['user_code'], unique=True)
        batch_op.create_foreign_key('fk_workers_user_code', 'users', ['user_code'], ['code'], ondelete='SET NULL')

    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO workers (name, category, role_key, source, user_code, created_at)
        SELECT u.name, 'staff', u.role_key, 'user_account', u.code, CURRENT_TIMESTAMP
        FROM users u
        WHERE u.is_admin = 0
          AND NOT EXISTS (SELECT 1 FROM workers w WHERE w.user_code = u.code)
    """))


def downgrade():
    op.execute("DELETE FROM workers WHERE source = 'user_account'")
    with op.batch_alter_table('workers', schema=None) as batch_op:
        batch_op.drop_constraint('fk_workers_user_code', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_workers_user_code'))
        batch_op.drop_column('user_code')
