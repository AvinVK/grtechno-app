"""site details move from leads to lead_surveys - captured at the survey, not the enquiry

Revision ID: d9b4e6f2a831
Revises: c9a1e5f7b283
Create Date: 2026-09-30 00:00:00.000000

Existing site_* data on a lead is copied onto its survey row (creating an empty one if the
lead has none yet) before the columns are dropped from leads, so nothing already entered is
lost.
"""
from alembic import op
import sqlalchemy as sa

from datetime import datetime


revision = 'd9b4e6f2a831'
down_revision = 'c9a1e5f7b283'
branch_labels = None
depends_on = None

SITE_COLUMNS = [
    ('site_category', sa.String(length=60)),
    ('site_pincode', sa.String(length=6)),
    ('site_state', sa.String(length=80)),
    ('site_district', sa.String(length=80)),
    ('site_city', sa.String(length=120)),
    ('site_address', sa.Text()),
]


def _columns(conn, table):
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    # SQLite's batch recreate rebuilds the whole table (drop + recreate), and with FK enforcement on
    # (this app turns it on for every connection - see app/extensions.py) that drop cascades through
    # ON DELETE CASCADE into lead_surveys (from leads) and survey_photos (from lead_surveys), wiping
    # rows that have nothing to do with the columns being touched. Off for the duration of this
    # migration only.
    op.execute("PRAGMA foreign_keys=OFF")
    conn = op.get_bind()

    # Defensive: an interrupted earlier attempt (killed mid-batch, or a name collision) can leave a
    # stale temp table behind, or the lead_surveys columns already added - either would make a retry
    # fail immediately without this. Safe to re-run from any of those partial states.
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_leads"))
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_lead_surveys"))

    missing = [(name, col_type) for name, col_type in SITE_COLUMNS if name not in _columns(conn, 'lead_surveys')]
    if missing:
        with op.batch_alter_table('lead_surveys', schema=None) as batch_op:
            for name, col_type in missing:
                batch_op.add_column(sa.Column(name, col_type, server_default='', nullable=False))

    if 'site_category' not in _columns(conn, 'leads'):
        op.execute("PRAGMA foreign_keys=ON")
        return                                          # a previous attempt already finished this part

    leads = conn.execute(sa.text(
        "SELECT id, site_category, site_pincode, site_state, site_district, site_city, site_address "
        "FROM leads"
    )).fetchall()
    for lead_id, category, pincode, state, district, city, address in leads:
        if not any([category, pincode, state, district, city, address]):
            continue
        existing = conn.execute(
            sa.text("SELECT id FROM lead_surveys WHERE lead_id = :lead_id"), {"lead_id": lead_id},
        ).fetchone()
        params = {
            "category": category, "pincode": pincode, "state": state, "district": district,
            "city": city, "address": address,
        }
        if existing:
            conn.execute(sa.text(
                "UPDATE lead_surveys SET site_category=:category, site_pincode=:pincode, "
                "site_state=:state, site_district=:district, site_city=:city, site_address=:address "
                "WHERE id=:id"
            ), {**params, "id": existing[0]})
        else:
            conn.execute(sa.text(
                "INSERT INTO lead_surveys (lead_id, rep_name, rep_role, rep_phone, "
                "site_category, site_pincode, site_state, site_district, site_city, site_address, created_at) "
                "VALUES (:lead_id, '', '', '', :category, :pincode, :state, :district, :city, :address, :created_at)"
            ), {**params, "lead_id": lead_id, "created_at": datetime.utcnow()})

    with op.batch_alter_table('leads', schema=None) as batch_op:
        for name, _ in SITE_COLUMNS:
            batch_op.drop_column(name)

    op.execute("PRAGMA foreign_keys=ON")


def downgrade():
    op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table('leads', schema=None) as batch_op:
        for name, col_type in SITE_COLUMNS:
            batch_op.add_column(sa.Column(name, col_type, server_default='', nullable=False))

    conn = op.get_bind()
    surveys = conn.execute(sa.text(
        "SELECT lead_id, site_category, site_pincode, site_state, site_district, site_city, site_address "
        "FROM lead_surveys"
    )).fetchall()
    for lead_id, category, pincode, state, district, city, address in surveys:
        conn.execute(sa.text(
            "UPDATE leads SET site_category=:category, site_pincode=:pincode, site_state=:state, "
            "site_district=:district, site_city=:city, site_address=:address WHERE id=:lead_id"
        ), {
            "category": category, "pincode": pincode, "state": state, "district": district,
            "city": city, "address": address, "lead_id": lead_id,
        })

    with op.batch_alter_table('lead_surveys', schema=None) as batch_op:
        for name, _ in SITE_COLUMNS:
            batch_op.drop_column(name)

    op.execute("PRAGMA foreign_keys=ON")
