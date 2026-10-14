"""Drop attendance's one-row-per-person-per-day constraint - checking in and out more than once in a day
(a lunch break, a second site) now makes a second row for the same day instead of being refused. See
app/attendance.py (check_in now only refuses a *second open* session, not a second row) and
app/models.py's Attendance docstring.

Revision ID: b9d4c2a71e03
Revises: a1c7e4f9b230
Create Date: 2026-10-14 00:00:00.000000
"""
from alembic import op


revision = 'b9d4c2a71e03'
down_revision = 'a1c7e4f9b230'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_constraint('uq_attendance_user_date', type_='unique')


def downgrade():
    """Not reversible if anyone now has more than one row for the same day - the whole point of this
    migration. Re-add the constraint only once any such duplicates have been dealt with by hand."""
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_attendance_user_date', ['user_code', 'work_date'])
