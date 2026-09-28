"""lead work order & advance: the pipeline stage between negotiation and won

Revision ID: a8d4f2c6e9b1
Revises: c7f3a9e2d514
Create Date: 2026-09-28 00:00:00.000000

Purely additive: four new columns on leads, all nullable or defaulted, so every existing lead reads
back exactly as it did before. See app/models.py and app/constants.py for the fuller story - winning a
lead now requires a work order number/date and an advance amount/date to be on file first.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a8d4f2c6e9b1'
down_revision = 'c7f3a9e2d514'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('work_order_no', sa.String(length=60), server_default='', nullable=False))
        batch_op.add_column(sa.Column('work_order_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('advance_amount', sa.Numeric(14, 2), nullable=True))
        batch_op.add_column(sa.Column('advance_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_column('advance_date')
        batch_op.drop_column('advance_amount')
        batch_op.drop_column('work_order_date')
        batch_op.drop_column('work_order_no')
