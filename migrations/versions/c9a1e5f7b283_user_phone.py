"""user phone: contact number shown on the signed-in person's own profile

Revision ID: c9a1e5f7b283
Revises: b3e7c1a9f452
Create Date: 2026-09-30 00:00:00.000000

Self-editable via the new View profile screen; encrypted at rest like the other phone columns.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9a1e5f7b283'
down_revision = 'b3e7c1a9f452'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('phone', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('phone')
