"""project stage pause/reason (kohal, 2026-10-22: "add pause button after each stage. if paused then whats
the reason? payment not recieved, manpower shortage, material shortage") - current pause state only, not a
log of every past pause. See app/models.py's ProjectStage and app/constants.py's PAUSE_REASONS.

Revision ID: f7b2e4a918c6
Revises: d41c8f93a7b0
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'f7b2e4a918c6'
down_revision = 'd41c8f93a7b0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('project_stages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('paused', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('pause_reason', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('pause_note', sa.Text(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('paused_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('project_stages', schema=None) as batch_op:
        batch_op.drop_column('paused_at')
        batch_op.drop_column('pause_note')
        batch_op.drop_column('pause_reason')
        batch_op.drop_column('paused')
