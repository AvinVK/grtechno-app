"""lead pipeline rework: multi-service, site survey with photos, negotiation rounds, lead->existing client

Revision ID: c2d8f4a9e136
Revises: a3c7e9f1b026
Create Date: 2026-09-26 00:00:00.000000

Purely additive: two new nullable columns on leads, and five new tables. Nothing existing is renamed,
retyped or dropped, so every current lead/client/project reads back exactly as it did before - the new
fields just come back empty for them. See app/models.py for the fuller story on why (Lead.service and
Project.work_category stay as legacy single-value fallbacks; new leads/projects use the new services
tables instead).
"""
from alembic import op
import sqlalchemy as sa


revision = 'c2d8f4a9e136'
down_revision = 'a3c7e9f1b026'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('quote_sent_date', sa.Date(), nullable=True))
        batch_op.create_index('ix_leads_client_id', ['client_id'])

    op.create_table(
        'lead_services',
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('lead_id', 'service_id'),
    )

    op.create_table(
        'project_services',
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('project_id', 'service_id'),
    )

    op.create_table(
        'lead_surveys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('survey_date', sa.Date(), nullable=True),
        sa.Column('surveyor_id', sa.Integer(), nullable=True),
        sa.Column('rep_name', sa.String(length=120), server_default='', nullable=False),
        sa.Column('rep_role', sa.String(length=60), server_default='', nullable=False),
        sa.Column('rep_phone', sa.String(length=40), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['surveyor_id'], ['workers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lead_id', name='uq_lead_surveys_lead_id'),
    )

    op.create_table(
        'survey_photos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('survey_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['survey_id'], ['lead_surveys.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_survey_photos_survey_id', 'survey_photos', ['survey_id'])

    op.create_table(
        'lead_negotiations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('round_no', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=True),
        sa.Column('authorized_person', sa.String(length=120), server_default='', nullable=False),
        sa.Column('estimate', sa.Numeric(14, 2), nullable=True),
        sa.Column('finalized', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lead_negotiations_lead_id', 'lead_negotiations', ['lead_id'])


def downgrade():
    op.drop_index('ix_lead_negotiations_lead_id', table_name='lead_negotiations')
    op.drop_table('lead_negotiations')
    op.drop_index('ix_survey_photos_survey_id', table_name='survey_photos')
    op.drop_table('survey_photos')
    op.drop_table('lead_surveys')
    op.drop_table('project_services')
    op.drop_table('lead_services')
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_index('ix_leads_client_id')
        batch_op.drop_column('quote_sent_date')
        batch_op.drop_column('client_id')
