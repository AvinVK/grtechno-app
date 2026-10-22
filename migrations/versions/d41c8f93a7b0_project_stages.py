"""project progress stages (kohal, 2026-10-22: the Progress tab's real content - a fixed 9-stage
installation checklist, same for every project, with an admin-set day count per stage, a manual mark-done,
and work photos at each phase). One row per (project, stage_key), created lazily the first time the admin
touches that stage - see app/models.py's ProjectStage/ProjectStagePhoto, Project.stage_rows, and
app/constants.py's PROJECT_STAGES for the fixed list of stage_key values.

Revision ID: d41c8f93a7b0
Revises: e5a9c3f7b162
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'd41c8f93a7b0'
down_revision = 'e5a9c3f7b162'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'project_stages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('stage_key', sa.String(length=40), nullable=False),
        sa.Column('days', sa.Integer(), nullable=True),
        sa.Column('done', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'stage_key', name='uq_project_stages_project_stage'),
    )
    with op.batch_alter_table('project_stages', schema=None) as batch_op:
        batch_op.create_index('ix_project_stages_project_id', ['project_id'])

    op.create_table(
        'project_stage_photos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stage_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['stage_id'], ['project_stages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('project_stage_photos', schema=None) as batch_op:
        batch_op.create_index('ix_project_stage_photos_stage_id', ['stage_id'])


def downgrade():
    with op.batch_alter_table('project_stage_photos', schema=None) as batch_op:
        batch_op.drop_index('ix_project_stage_photos_stage_id')
    op.drop_table('project_stage_photos')

    with op.batch_alter_table('project_stages', schema=None) as batch_op:
        batch_op.drop_index('ix_project_stages_project_id')
    op.drop_table('project_stages')
