"""Commission given to anyone by name (kohal, 2026-11-09: "the person should be a text name and not a drop down. commission can be
any person outside org as well"). One new column, empty for every existing entry; nothing existing is changed.

Revision ID: b8f3d6a2c714
Revises: a7e2c5f9d641
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8f3d6a2c714'
down_revision = 'a7e2c5f9d641'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('project_expenses', sa.Column('person_name', sa.String(length=120), nullable=False, server_default=''))


def downgrade():
    op.drop_column('project_expenses', 'person_name')
