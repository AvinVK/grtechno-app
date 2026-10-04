"""more site categories; clients get a site name; typed-in categories wait for admin approval

Revision ID: 0a713797f60c
Revises: eff82647a228
Create Date: 2026-10-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0a713797f60c'
down_revision = 'eff82647a228'
branch_labels = None
depends_on = None

# A copy, not an import of app code; tests/test_reference_data.py checks it matches app/reference_data.py.
SITE_CATEGORIES = [
    "Hospital", "Nursing home", "Residential apartment", "Commercial complex",
    "School", "Educational institute", "Plant", "Industry", "Residential", "Commercial", "Multi dwelling unit",
    "Other",
]


def _columns(conn, table):
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_clients"))
    if 'site_name' not in _columns(conn, 'clients'):
        with op.batch_alter_table('clients', schema=None) as batch_op:
            batch_op.add_column(sa.Column('site_name', sa.String(length=160), server_default='', nullable=False))

    for name in SITE_CATEGORIES:
        if not conn.execute(sa.text("SELECT 1 FROM site_categories WHERE name = :n"), {'n': name}).first():
            conn.execute(sa.text("INSERT INTO site_categories (name, sort_order, is_active) VALUES (:n, 0, 1)"), {'n': name})
    for i, name in enumerate(SITE_CATEGORIES, start=1):
        conn.execute(sa.text("UPDATE site_categories SET sort_order = :o, is_active = 1 WHERE name = :n"), {'o': i, 'n': name})

    if not conn.dialect.has_table(conn, 'site_category_requests'):
        op.create_table(
            'site_category_requests',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=60), nullable=False),
            sa.Column('requested_by_code', sa.String(length=4), nullable=True),
            sa.Column('status', sa.String(length=12), server_default='pending', nullable=False),
            sa.Column('target', sa.String(length=60), server_default='', nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['requested_by_code'], ['users.code'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_site_category_requests_name', 'site_category_requests', ['name'])
        op.create_index('ix_site_category_requests_status', 'site_category_requests', ['status'])


def downgrade():
    op.drop_index('ix_site_category_requests_status', table_name='site_category_requests')
    op.drop_index('ix_site_category_requests_name', table_name='site_category_requests')
    op.drop_table('site_category_requests')
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.drop_column('site_name')
