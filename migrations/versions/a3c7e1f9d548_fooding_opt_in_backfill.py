"""Backfill fooding_opt_in for existing daily-wage workers (kohal, 2026-10-18: "this fooding check should
be available for all employees. should be automatically on for daily wages and off for others. their
might be plans to remove the fooding option completely") - fooding_opt_in becomes the one source of truth
for Worker.fooding_eligible from here on, no longer also special-cased by employment_type == "daily_wages"
in code; a daily-wage worker already relying on that automatic rule needs the checkbox actually turned on
now, or they'd silently lose fooding eligibility the moment this ships.

One-way: there's no record of which rows this touches, so downgrade doesn't attempt to undo it.

Revision ID: a3c7e1f9d548
Revises: f1a6d8e4b259
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'a3c7e1f9d548'
down_revision = 'f1a6d8e4b259'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE workers SET fooding_opt_in = 1 WHERE employment_type = 'daily_wages'"))


def downgrade():
    pass
