"""Attendance approval (kohal, 2026-10-16: "Attendance should be approved by project manager or site
supervisor who is checked in on tha project"). A record is 'pending' until the admin, Company Director,
that project's manager, or a site supervisor currently checked into that exact project approves it (office/
marketing work needs the admin or Company Director, since there's no project to approve against) - it's
excluded from day/week counts until then, the same way a pending MaterialMovement is excluded from stock.
Every existing record, already counted, becomes 'approved'.

Revision ID: a7e3c9f2b584
Revises: f4c8a2e6d931
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7e3c9f2b584'
down_revision = 'f4c8a2e6d931'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=10), server_default='approved', nullable=False))
        batch_op.add_column(sa.Column('approved_by_code', sa.String(length=4), nullable=True))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            'fk_attendance_approved_by_code', 'users', ['approved_by_code'], ['code'], ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_constraint('fk_attendance_approved_by_code', type_='foreignkey')
        batch_op.drop_column('approved_at')
        batch_op.drop_column('approved_by_code')
        batch_op.drop_column('status')
