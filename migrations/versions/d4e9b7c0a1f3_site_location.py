"""site pincode, state, district and city on leads; pincodes lookup table

Revision ID: d4e9b7c0a1f3
Revises: c3f8a1b25d7e
Create Date: 2026-09-19 23:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e9b7c0a1f3'
down_revision = 'c3f8a1b25d7e'
branch_labels = None
depends_on = None

NEW_COLUMNS = [('site_pincode', 6), ('site_state', 80), ('site_district', 80), ('site_city', 120)]


def upgrade():
    op.create_table(
        'pincodes',
        sa.Column('pincode', sa.String(length=6), nullable=False),
        sa.Column('state', sa.String(length=80), nullable=False),
        sa.Column('district', sa.String(length=80), nullable=False),
        sa.Column('city', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('pincode'),
    )
    with op.batch_alter_table('leads', schema=None) as batch_op:
        for name, length in NEW_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.String(length=length), server_default='', nullable=False))


def downgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        for name, _ in NEW_COLUMNS:
            batch_op.drop_column(name)
    op.drop_table('pincodes')
