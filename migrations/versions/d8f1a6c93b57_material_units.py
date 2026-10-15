"""Material units - a short, growable list backing the Unit picker on Add/Edit material (kohal, 2026-10-15:
"for unit, need dropdown with these: Meter EA LOT JOB PCS KG ADD NEW").

Material.unit itself stays the plain string column it already was - this is just a reference table of
suggestions, seeded with the requested set. A migration must not depend on app code, so the seed list is
copy-pasted here rather than imported from reference_data.py.

Revision ID: d8f1a6c93b57
Revises: c3f6b1d8e4a7
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8f1a6c93b57'
down_revision = 'c3f6b1d8e4a7'
branch_labels = None
depends_on = None

SEED_UNITS = ("Meter", "EA", "LOT", "JOB", "PCS", "KG")


def upgrade():
    op.create_table(
        'material_units',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('name'),
    )
    conn = op.get_bind()
    for name in SEED_UNITS:
        conn.execute(sa.text(
            "INSERT INTO material_units (name, created_at) "
            "SELECT :name, CURRENT_TIMESTAMP WHERE NOT EXISTS "
            "(SELECT 1 FROM material_units WHERE lower(name) = lower(:name))"
        ), {"name": name})


def downgrade():
    op.drop_table('material_units')
