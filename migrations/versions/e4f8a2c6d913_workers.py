"""workers and worker_attendance: field workers tracked from WhatsApp, not app logins

Revision ID: e4f8a2c6d913
Revises: d2e9c4b7f105
Create Date: 2026-09-23 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e4f8a2c6d913'
down_revision = 'd2e9c4b7f105'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'workers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('source', sa.String(length=30), server_default='whatsapp', nullable=False),
        sa.Column('first_seen', sa.Date(), nullable=True),
        sa.Column('last_seen', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'worker_attendance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('check_in_at', sa.DateTime(), nullable=True),
        sa.Column('check_in_lat', sa.Float(), nullable=True),
        sa.Column('check_in_lng', sa.Float(), nullable=True),
        sa.Column('check_out_at', sa.DateTime(), nullable=True),
        sa.Column('check_out_lat', sa.Float(), nullable=True),
        sa.Column('check_out_lng', sa.Float(), nullable=True),
        sa.Column('note', sa.String(length=300), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('worker_id', 'work_date', name='uq_worker_attendance_worker_date'),
    )
    op.create_index('ix_worker_attendance_worker_id', 'worker_attendance', ['worker_id'])
    op.create_index('ix_worker_attendance_work_date', 'worker_attendance', ['work_date'])


def downgrade():
    op.drop_table('worker_attendance')
    op.drop_table('workers')
