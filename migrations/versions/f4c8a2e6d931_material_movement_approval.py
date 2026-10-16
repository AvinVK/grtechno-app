"""Material movement approval (kohal, 2026-10-16): issuing material to a project needs sign-off from the
site supervisor currently checked into that project or its project manager; stocking material in needs
sign-off from an accountant or office assistant. A movement is 'pending' until approved - excluded from
stock_qty/avg_rate until then - or 'rejected', permanently. Every existing movement, already reflected in
stock, becomes 'approved'.

Revision ID: f4c8a2e6d931
Revises: e2b4a8c17f93
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4c8a2e6d931'
down_revision = 'e2b4a8c17f93'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=10), server_default='approved', nullable=False))
        batch_op.add_column(sa.Column('approved_by_code', sa.String(length=4), nullable=True))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            'fk_material_movements_approved_by_code', 'users', ['approved_by_code'], ['code'], ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.drop_constraint('fk_material_movements_approved_by_code', type_='foreignkey')
        batch_op.drop_column('approved_at')
        batch_op.drop_column('approved_by_code')
        batch_op.drop_column('status')
