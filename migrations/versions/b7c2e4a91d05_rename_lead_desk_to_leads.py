"""rename the Lead desk service to Leads

Revision ID: b7c2e4a91d05
Revises: a8d4f1c6e932
Create Date: 2026-09-20 18:00:00.000000

"""
from alembic import op


revision = 'b7c2e4a91d05'
down_revision = 'a8d4f1c6e932'
branch_labels = None
depends_on = None


def upgrade():
    # Only while it still has the original name, so a name the admin chose is never overwritten.
    op.execute("UPDATE modules SET name = 'Leads' WHERE key = 'leads' AND name = 'Lead desk'")


def downgrade():
    op.execute("UPDATE modules SET name = 'Lead desk' WHERE key = 'leads' AND name = 'Leads'")
