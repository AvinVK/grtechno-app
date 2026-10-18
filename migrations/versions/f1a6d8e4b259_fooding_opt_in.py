"""workers.fooding_opt_in (kohal, 2026-10-18): a salaried or contractor employee can opt onto the same
₹200/day fooding wallet a daily-wage worker already gets automatically.

Revision ID: f1a6d8e4b259
Revises: e9b4f8d2c637
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a6d8e4b259'
down_revision = 'e9b4f8d2c637'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fooding_opt_in', sa.Boolean(), server_default='0', nullable=False))


def downgrade():
    with op.batch_alter_table('workers', schema=None) as batch_op:
        batch_op.drop_column('fooding_opt_in')
