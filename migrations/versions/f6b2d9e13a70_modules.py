"""modules table: the services listed in the sidebar

Revision ID: f6b2d9e13a70
Revises: e5a1c8d2b6f4
Create Date: 2026-09-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f6b2d9e13a70'
down_revision = 'e5a1c8d2b6f4'
branch_labels = None
depends_on = None


def upgrade():
    modules = op.create_table(
        'modules',
        sa.Column('key', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('icon', sa.String(length=30), server_default='grid', nullable=False),
        sa.Column('path', sa.String(length=120), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('admin_only', sa.Boolean(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    op.bulk_insert(modules, [
        {'key': 'leads', 'name': 'Lead desk', 'icon': 'leads', 'path': '/', 'sort_order': 1, 'is_active': True, 'admin_only': False},
    ])


def downgrade():
    op.drop_table('modules')
