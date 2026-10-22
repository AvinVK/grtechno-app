"""project stage remarks (kohal, 2026-10-22: "add note at each step") - a free admin note per stage,
separate from pause_note (only set alongside a pause) and from PROJECT_STAGES' own fixed hint text. See
app/models.py's ProjectStage.remarks.

Revision ID: a93c5d7e2f14
Revises: f7b2e4a918c6
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'a93c5d7e2f14'
down_revision = 'f7b2e4a918c6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('project_stages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('remarks', sa.Text(), nullable=False, server_default=''))


def downgrade():
    with op.batch_alter_table('project_stages', schema=None) as batch_op:
        batch_op.drop_column('remarks')
