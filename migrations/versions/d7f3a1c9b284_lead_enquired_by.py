"""leads.enquired_by_id: who from the staff list took the enquiry, defaults the site survey's surveyor

Revision ID: d7f3a1c9b284
Revises: c2d8f4a9e136
Create Date: 2026-09-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd7f3a1c9b284'
down_revision = 'c2d8f4a9e136'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('enquired_by_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_column('enquired_by_id')
