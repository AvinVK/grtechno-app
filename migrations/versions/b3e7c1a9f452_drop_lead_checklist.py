"""drop lead checklist: removed from the lead flow

Revision ID: b3e7c1a9f452
Revises: a8d4f2c6e9b1
Create Date: 2026-09-28 00:10:00.000000

The per-lead checklist never carried over into a project and wasn't used - dropping the table outright.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3e7c1a9f452'
down_revision = 'a8d4f2c6e9b1'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('lead_checklist_items')


def downgrade():
    op.create_table(
        'lead_checklist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(length=200), nullable=False),
        sa.Column('done', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lead_checklist_items_lead_id', 'lead_checklist_items', ['lead_id'])
