"""adhoc clients (kohal, 2026-10-30: "adhoc clients in client tab... supply of extinguisher and refilling of
extinguisher... once the client is added, its respective adhoc project should also be added... primary key
will be client's contact number") - one new flag on clients (default off, so every existing client stays a
normal client) and one new table, adhoc_items: the extinguishers or fire material on an adhoc project (type,
weight/spec, quantity, rate, and for a refill the refilling, HPT and expiry dates). Adds only; nothing existing
is touched or rewritten.

Revision ID: b3d7f1a9c524
Revises: a5c9e3b7d186
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3d7f1a9c524'
down_revision = 'a5c9e3b7d186'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clients', sa.Column('is_adhoc', sa.Boolean(), nullable=False, server_default='0'))
    op.create_table(
        'adhoc_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('fe_type', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('weight', sa.String(length=60), nullable=False, server_default=''),
        sa.Column('qty', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('rate', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('refill_date', sa.Date(), nullable=True),
        sa.Column('hpt_date', sa.Date(), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('remark', sa.String(length=400), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_adhoc_items_project_id', 'adhoc_items', ['project_id'])


def downgrade():
    op.drop_index('ix_adhoc_items_project_id', table_name='adhoc_items')
    op.drop_table('adhoc_items')
    op.drop_column('clients', 'is_adhoc')
