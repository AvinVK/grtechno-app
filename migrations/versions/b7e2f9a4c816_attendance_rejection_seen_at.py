"""attendance.rejection_seen_at (kohal, 2026-10-20: "a popup as soon as attendance was rejected so that
user knows") - marks when the person themselves has seen a popup about their own rejected check-in, so it
only shows once; see app/static/js/common.js.

Backfill marks every already-rejected record as already seen (at its own approved_at, when it was decided)
- without this, shipping the popup would surface every pre-existing rejection all at once, most of them
long since moot, instead of only new ones from here on."""
from alembic import op
import sqlalchemy as sa

revision = 'b7e2f9a4c816'
down_revision = 'a8e5d3b7f204'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rejection_seen_at', sa.DateTime(), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE attendance SET rejection_seen_at = approved_at WHERE status = 'rejected'"))


def downgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_column('rejection_seen_at')
