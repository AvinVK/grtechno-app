"""adhoc items' GST and the order's installation / transportation charges (kohal, 2026-10-31) - one new column on
adhoc_items (gst_percent) and two on projects. Existing rows start at 0, so nothing already saved changes value.
Adds columns only.

Revision ID: d5f9b3e7a042
Revises: c4e8a2d6f931
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5f9b3e7a042'
down_revision = 'c4e8a2d6f931'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('adhoc_items', sa.Column('gst_percent', sa.Numeric(5, 2), nullable=False, server_default='0'))
    op.add_column('projects', sa.Column('installation_charge', sa.Numeric(14, 2), nullable=False, server_default='0'))
    op.add_column('projects', sa.Column('transport_charge', sa.Numeric(14, 2), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('projects', 'transport_charge')
    op.drop_column('projects', 'installation_charge')
    op.drop_column('adhoc_items', 'gst_percent')
