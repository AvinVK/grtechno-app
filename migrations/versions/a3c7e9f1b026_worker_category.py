"""workers: category (manpower | staff) - the same table now backs two separate lists

Revision ID: a3c7e9f1b026
Revises: f7b3d5e2a084
Create Date: 2026-09-24 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3c7e9f1b026'
down_revision = 'f7b3d5e2a084'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.String(length=20), server_default='manpower', nullable=False))


def downgrade():
    with op.batch_alter_table('workers', schema=None) as batch_op:
        batch_op.drop_column('category')
