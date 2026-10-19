"""material_movements.requested (kohal, 2026-10-19: "requetor and creator are the same still somehow") -
tells a project's own material request apart from a direct issue from Inventory itself, which always
self-approves by design and was getting shown in the Material requests tab's history as if it were a
self-approved request (right after self-approval had just been turned off for requests specifically).

Backfill is best-effort, since nothing on the existing rows says which is which: a rejected 'out' row, or
one approved by someone other than whoever created it, could only ever have come from the request+approval
flow (a direct issue is always self-approved, never rejected) - so those become requested=True. A
self-approved 'out' row is ambiguous (it could be an old pre-fix self-approved request, or a genuine direct
issue) and defaults to requested=False, the safer choice - it just stops showing in the Material requests
tab's history, same as it would if it really were a direct issue; it's still visible on the material's own
movement history either way. Every currently-pending 'out' row is unambiguous (a direct issue is never
pending) and becomes requested=True.

Revision ID: d2f8a4c6e913
Revises: c9d3e7f1a254
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'd2f8a4c6e913'
down_revision = 'c9d3e7f1a254'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('requested', sa.Boolean(), server_default='0', nullable=False))

    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE material_movements
        SET requested = 1
        WHERE kind = 'out' AND (
            status = 'pending'
            OR status = 'rejected'
            OR (approved_by_code IS NOT NULL AND created_by_code IS NOT NULL AND approved_by_code != created_by_code)
        )
    """))


def downgrade():
    with op.batch_alter_table('material_movements', schema=None) as batch_op:
        batch_op.drop_column('requested')
