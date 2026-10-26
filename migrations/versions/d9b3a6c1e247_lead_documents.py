"""lead documents (kohal, 2026-10-26: "upload work order (BOQ) and purchase order during work order step in
lead flow") - one row per (lead, doc_type), re-uploading the same type replaces it. They carry over to the
project's own documents when the lead is won (app/projects.py). Adds a table only; nothing existing is
touched.

Revision ID: d9b3a6c1e247
Revises: c2a8f5e713d9
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'd9b3a6c1e247'
down_revision = 'c2a8f5e713d9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lead_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('doc_type', sa.String(length=30), nullable=False),
        sa.Column('filename', sa.String(length=80), nullable=False),
        sa.Column('uploaded_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lead_id', 'doc_type', name='uq_lead_documents_lead_type'),
    )
    op.create_index('ix_lead_documents_lead_id', 'lead_documents', ['lead_id'])


def downgrade():
    op.drop_index('ix_lead_documents_lead_id', table_name='lead_documents')
    op.drop_table('lead_documents')
