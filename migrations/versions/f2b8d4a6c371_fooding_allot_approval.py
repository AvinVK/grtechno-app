"""fooding allotments need approval (kohal, 2026-10-27: "when allocating fooding money, the allocated amount needs
to be approved by either admin or accountant. if admin gives, accountant can approve or vice versa") - three
new columns on fooding_entries: status (pending | approved | rejected | cancelled), who decided and when. Every
existing row keeps counting: the status column defaults to 'approved', so no entry that already moved money
changes. Adds columns only; nothing is rewritten.

Revision ID: f2b8d4a6c371
Revises: e1a7c3b9d452
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'f2b8d4a6c371'
down_revision = 'e1a7c3b9d452'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('fooding_entries', sa.Column('status', sa.String(length=10), nullable=False, server_default='approved'))
    op.add_column('fooding_entries', sa.Column('decided_by_code', sa.String(length=4), nullable=True))
    op.add_column('fooding_entries', sa.Column('decided_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('fooding_entries', 'decided_at')
    op.drop_column('fooding_entries', 'decided_by_code')
    op.drop_column('fooding_entries', 'status')
