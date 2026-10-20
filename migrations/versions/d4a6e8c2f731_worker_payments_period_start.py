"""worker_payments.period_start (kohal, 2026-10-20: "Daily wages should have two slots in month 1 to 15
And 16 to 30 or 31") - which half-month pay period a payment entry covers, as that period's own first day
(the 1st or the 16th); null for one not tied to a period (a salaried employee's, or an older entry from
before this existed). See app/payroll.py for how Overview matches a payment back to its slot.

Revision ID: d4a6e8c2f731
Revises: b7e2f9a4c816
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4a6e8c2f731'
down_revision = 'b7e2f9a4c816'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('worker_payments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('period_start', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('worker_payments', schema=None) as batch_op:
        batch_op.drop_column('period_start')
