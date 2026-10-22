"""project stage scheduled payment (kohal, 2026-10-22: "give an option of adding 'add sheduled payment'
checkbox after every step. and only when that payment is marked as recived it should move to next step,
until then it should show please pay for the project to move to next step") - its own fields on
project_stages, not a link into the project's payment schedule (see app/models.py's ProjectStage docstring
for why).

Revision ID: b6e4d928a3f7
Revises: a93c5d7e2f14
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6e4d928a3f7'
down_revision = 'a93c5d7e2f14'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('project_stages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_required', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('payment_amount', sa.Numeric(precision=14, scale=2), nullable=True))
        batch_op.add_column(sa.Column('payment_due_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('payment_received_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('project_stages', schema=None) as batch_op:
        batch_op.drop_column('payment_received_at')
        batch_op.drop_column('payment_due_date')
        batch_op.drop_column('payment_amount')
        batch_op.drop_column('payment_required')
