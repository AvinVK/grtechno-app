"""attendance: where a check-in happened

Revision ID: d2e9c4b7f105
Revises: c1d5f8a3b6e2
Create Date: 2026-09-24 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd2e9c4b7f105'
down_revision = 'c1d5f8a3b6e2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('check_in_lat', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('check_in_lng', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_column('check_in_lng')
        batch_op.drop_column('check_in_lat')
