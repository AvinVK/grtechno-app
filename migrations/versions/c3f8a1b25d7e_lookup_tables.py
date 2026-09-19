"""services and lead_sources tables; settings holds currency and country_code rows

Revision ID: c3f8a1b25d7e
Revises: a139ace11c38
Create Date: 2026-09-19 22:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3f8a1b25d7e'
down_revision = 'a139ace11c38'
branch_labels = None
depends_on = None

DEFAULT_SERVICES = [
    "Sprinklers", "Fire alarms", "Hydrant and pump room", "Extinguishers",
    "Gas suppression", "NOC and audits", "AMC",
]
DEFAULT_SOURCES = [
    "Referral", "Website", "Walk-in", "Cold call", "Tender / RFQ",
    "Repeat client", "Consultant / architect",
]


def _option_table(name):
    return op.create_table(
        name,
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )


def _lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def upgrade():
    services = _option_table('services')
    sources = _option_table('lead_sources')

    bind = op.get_bind()
    saved = {k: v for k, v in bind.execute(sa.text('SELECT "key", value FROM settings')).fetchall()}

    def rows(names):
        return [{'name': n, 'sort_order': i, 'is_active': True} for i, n in enumerate(names, start=1)]

    op.bulk_insert(services, rows(_lines(saved.get('services')) or DEFAULT_SERVICES))
    op.bulk_insert(sources, rows(_lines(saved.get('sources')) or DEFAULT_SOURCES))

    bind.execute(sa.text('DELETE FROM settings WHERE "key" IN (\'services\', \'sources\')'))
    for key, default in (('currency', '₹'), ('country_code', '91')):
        if key not in saved:
            bind.execute(sa.text('INSERT INTO settings ("key", value) VALUES (:k, :v)'), {'k': key, 'v': default})


def downgrade():
    bind = op.get_bind()
    for key, table in (('services', 'services'), ('sources', 'lead_sources')):
        names = [r[0] for r in bind.execute(sa.text(f'SELECT name FROM {table} ORDER BY sort_order, name')).fetchall()]
        bind.execute(sa.text('INSERT INTO settings ("key", value) VALUES (:k, :v)'), {'k': key, 'v': "\n".join(names)})
    op.drop_table('lead_sources')
    op.drop_table('services')
