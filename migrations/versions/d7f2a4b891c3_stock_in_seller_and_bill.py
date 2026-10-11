"""Stock-in movements: who it was bought from (seller name/contact) and the bill - a material can be
restocked from a different seller each time, so these live on the movement, not the material itself.

Revision ID: d7f2a4b891c3
Revises: c4a1d7e3f958
Create Date: 2026-10-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd7f2a4b891c3'
down_revision = 'c4a1d7e3f958'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seller_name', sa.String(length=120), server_default='', nullable=False))
        batch_op.add_column(sa.Column('seller_contact', sa.String(length=40), server_default='', nullable=False))
        batch_op.add_column(sa.Column('bill_filename', sa.String(length=80), nullable=True))


def downgrade():
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.drop_column('bill_filename')
        batch_op.drop_column('seller_contact')
        batch_op.drop_column('seller_name')
