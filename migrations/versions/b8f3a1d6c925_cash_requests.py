"""cash requests (kohal, 2026-10-21: "add cash request for employees so that admin sees the request and
then alocates... the flow is employee requests for cash, admin sees the request -> allocates money ->
employees logs expense -> admin approves") - one table, closed out as fulfilled by give() or turned down
by reject_request(). See app/models.py's CashRequest for the full story.

Revision ID: b8f3a1d6c925
Revises: a2c7f1e9b543
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8f3a1d6c925'
down_revision = 'a2c7f1e9b543'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cash_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('note', sa.String(length=500), server_default='', nullable=False),
        sa.Column('status', sa.String(length=10), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by_code', sa.String(length=4), nullable=True),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resolved_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('cash_requests', schema=None) as batch_op:
        batch_op.create_index('ix_cash_requests_worker_id', ['worker_id'])


def downgrade():
    with op.batch_alter_table('cash_requests', schema=None) as batch_op:
        batch_op.drop_index('ix_cash_requests_worker_id')
    op.drop_table('cash_requests')
