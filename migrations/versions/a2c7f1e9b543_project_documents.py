"""project closing documents (kohal, 2026-10-21: "when closing the project, need to mandatorily upload
these 3 things once measure done = true. final estimate, work completion certi, final invoice mandatory
upload") - one row per (project, doc_type), re-uploading the same type replaces it. See
app/models.py's ProjectDocument and app/constants.py's PROJECT_DOCUMENT_TYPES for the fixed list of types,
and app/projects.py's close_project for the gate this backs.

Revision ID: a2c7f1e9b543
Revises: fe3d625d936b
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2c7f1e9b543'
down_revision = 'fe3d625d936b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'project_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('doc_type', sa.String(length=30), nullable=False),
        sa.Column('filename', sa.String(length=80), nullable=False),
        sa.Column('uploaded_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'doc_type', name='uq_project_documents_project_type'),
    )
    with op.batch_alter_table('project_documents', schema=None) as batch_op:
        batch_op.create_index('ix_project_documents_project_id', ['project_id'])


def downgrade():
    with op.batch_alter_table('project_documents', schema=None) as batch_op:
        batch_op.drop_index('ix_project_documents_project_id')
    op.drop_table('project_documents')
