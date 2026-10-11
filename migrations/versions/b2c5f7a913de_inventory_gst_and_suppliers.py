"""Inventory: a Supplier reference table (same "add new on the fly" pattern as Role), and GST/bill/payment
fields on a stock-in movement, plus who gave material out on an issue. seller_name/seller_contact are
dropped in favour of a real supplier_id, and Material.code is a computed property (MAT-0001, from id), not
a stored column, so it needs no migration of its own.

Revision ID: b2c5f7a913de
Revises: d7f2a4b891c3
Create Date: 2026-10-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c5f7a913de'
down_revision = 'd7f2a4b891c3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'suppliers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('supplier_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('bill_no', sa.String(length=60), server_default='', nullable=False))
        batch_op.add_column(sa.Column('payment_mode', sa.String(length=10), server_default='', nullable=False))
        batch_op.add_column(sa.Column('gst_percent', sa.Numeric(precision=5, scale=2), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('gst_amount', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('total_cost', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('given_by_worker_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_material_movements_supplier_id'), ['supplier_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_material_movements_given_by_worker_id'), ['given_by_worker_id'], unique=False)
        batch_op.create_foreign_key('fk_material_movements_supplier_id', 'suppliers', ['supplier_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_material_movements_given_by_worker_id', 'workers', ['given_by_worker_id'], ['id'], ondelete='SET NULL')
        batch_op.drop_column('seller_contact')
        batch_op.drop_column('seller_name')
    op.execute('UPDATE material_movements SET total_cost = amount WHERE kind = \'in\'')


def downgrade():
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seller_name', sa.String(length=120), server_default='', nullable=False))
        batch_op.add_column(sa.Column('seller_contact', sa.String(length=40), server_default='', nullable=False))
        batch_op.drop_constraint('fk_material_movements_given_by_worker_id', type_='foreignkey')
        batch_op.drop_constraint('fk_material_movements_supplier_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_material_movements_given_by_worker_id'))
        batch_op.drop_index(batch_op.f('ix_material_movements_supplier_id'))
        batch_op.drop_column('given_by_worker_id')
        batch_op.drop_column('total_cost')
        batch_op.drop_column('gst_amount')
        batch_op.drop_column('gst_percent')
        batch_op.drop_column('payment_mode')
        batch_op.drop_column('bill_no')
        batch_op.drop_column('supplier_id')
    op.drop_table('suppliers')
