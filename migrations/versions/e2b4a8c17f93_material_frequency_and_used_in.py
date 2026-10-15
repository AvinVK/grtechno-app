"""Material frequency and used-in (kohal, 2026-10-15: "Add field frequency used in material - Every
project / Special project / Occasional" and "Add field Used in.. - Hydrant / Pump house / Sprinkler /
Fire alarm / Portable devices / Other..specify").

frequency is a small fixed key ("" / every_project / special_project / occasional). used_in is a JSON list
of strings in a plain text column - a material can be used in more than one system, so this isn't a single
choice; see Material.used_in_list and app/inventory.py.

Revision ID: e2b4a8c17f93
Revises: d8f1a6c93b57
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2b4a8c17f93'
down_revision = 'd8f1a6c93b57'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('materials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('frequency', sa.String(length=20), server_default='', nullable=False))
        batch_op.add_column(sa.Column('used_in', sa.Text(), server_default='', nullable=False))


def downgrade():
    with op.batch_alter_table('materials', schema=None) as batch_op:
        batch_op.drop_column('used_in')
        batch_op.drop_column('frequency')
