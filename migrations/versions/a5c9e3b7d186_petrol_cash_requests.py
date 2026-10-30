"""petrol cash requests (kohal, 2026-10-30: "after the odo readings are approved, the employee should get a
button to request for that amount of cash... only admin or accountant should be able to approve it... the
approver have to enter the mode of payment") - five new columns on petrol_entries: where the cash request
stands (empty = not asked, requested | paid | rejected), when it was asked, who decided and when, and how it
was paid. Every existing entry starts as 'not asked'. Adds columns only; nothing is rewritten.

Revision ID: a5c9e3b7d186
Revises: f2b8d4a6c371
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'a5c9e3b7d186'
down_revision = 'f2b8d4a6c371'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('petrol_entries', sa.Column('cash_status', sa.String(length=10), nullable=False, server_default=''))
    op.add_column('petrol_entries', sa.Column('cash_requested_at', sa.DateTime(), nullable=True))
    op.add_column('petrol_entries', sa.Column('cash_decided_by_code', sa.String(length=4), nullable=True))
    op.add_column('petrol_entries', sa.Column('cash_decided_at', sa.DateTime(), nullable=True))
    op.add_column('petrol_entries', sa.Column('cash_mode', sa.String(length=20), nullable=False, server_default=''))


def downgrade():
    op.drop_column('petrol_entries', 'cash_mode')
    op.drop_column('petrol_entries', 'cash_decided_at')
    op.drop_column('petrol_entries', 'cash_decided_by_code')
    op.drop_column('petrol_entries', 'cash_requested_at')
    op.drop_column('petrol_entries', 'cash_status')
