"""project_expenses table (kohal, 2026-10-18): money paid out of a project to someone connected to it, not
to the client - starts with commission (the Project manager Chandrapur role earns a percentage of a
project's negotiated amount, entered from the project's own Payment tab); daily wages and site food are
meant to land in this same table as more `kind`s later, not separate ones.

Revision ID: c8e3b1f6a729
Revises: b5f9d3a7c642
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'c8e3b1f6a729'
down_revision = 'b5f9d3a7c642'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'project_expenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), server_default='commission', nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=True),
        sa.Column('percent', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('basis_amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('note', sa.Text(), server_default='', nullable=False),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_project_expenses_project_id', 'project_expenses', ['project_id'])
    op.create_index('ix_project_expenses_worker_id', 'project_expenses', ['worker_id'])


def downgrade():
    op.drop_index('ix_project_expenses_worker_id', table_name='project_expenses')
    op.drop_index('ix_project_expenses_project_id', table_name='project_expenses')
    op.drop_table('project_expenses')
