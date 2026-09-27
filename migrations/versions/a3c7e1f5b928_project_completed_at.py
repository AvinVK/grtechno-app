"""projects.completed_at: when the project was closed (marked completed), for "ran for" on its dashboard

Revision ID: a3c7e1f5b928
Revises: d7f3a1c9b284
Create Date: 2026-09-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3c7e1f5b928'
down_revision = 'd7f3a1c9b284'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('completed_at', sa.DateTime(), nullable=True))
    # Projects already completed before this column existed: their last edit is the closest we have.
    op.execute("UPDATE projects SET completed_at = updated_at WHERE status = 'completed'")


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('completed_at')
