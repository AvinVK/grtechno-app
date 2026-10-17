"""Material movement transport detail (kohal, 2026-10-17): how a pending issue request was physically
carried out once approved from Inventory's own Material requests tab - transport_mode (own vehicle/company
vehicle/courier/hand carried/other) and transported_at (day and time), alongside the existing
given_by_worker_id (who took it).

Revision ID: b5f9d3a7c642
Revises: a7e3c9f2b584
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'b5f9d3a7c642'
down_revision = 'a7e3c9f2b584'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('transport_mode', sa.String(length=40), server_default='', nullable=False))
        batch_op.add_column(sa.Column('transported_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.drop_column('transported_at')
        batch_op.drop_column('transport_mode')
