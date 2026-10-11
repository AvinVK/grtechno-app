"""Inventory: materials bought in bulk, stocked, and issued out to projects as they're used. Admin only
for now - a new module row with admin_only set, no role_modules rows needed.

Revision ID: c4a1d7e3f958
Revises: b58e2d4a917c
Create Date: 2026-10-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4a1d7e3f958'
down_revision = 'b58e2d4a917c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'materials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('unit', sa.String(length=20), server_default='', nullable=False),
        sa.Column('stock_qty', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('avg_rate', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('notes', sa.String(length=400), server_default='', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'material_movements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('material_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('rate', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(length=200), server_default='', nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['material_id'], ['materials.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_material_movements_material_id', 'material_movements', ['material_id'])
    op.create_index('ix_material_movements_project_id', 'material_movements', ['project_id'])

    modules = sa.table('modules', sa.column('key'), sa.column('name'), sa.column('icon'), sa.column('path'),
                        sa.column('sort_order'), sa.column('is_active'), sa.column('admin_only'))
    op.bulk_insert(modules, [
        {'key': 'inventory', 'name': 'Inventory', 'icon': 'material', 'path': '/inventory',
         'sort_order': 5, 'is_active': True, 'admin_only': True},
    ])


def downgrade():
    op.get_bind().execute(sa.text("DELETE FROM modules WHERE key = 'inventory'"))
    op.drop_index('ix_material_movements_project_id', table_name='material_movements')
    op.drop_index('ix_material_movements_material_id', table_name='material_movements')
    op.drop_table('material_movements')
    op.drop_table('materials')
