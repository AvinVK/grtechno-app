"""announcements + announcement_recipients (kohal, 2026-10-19: "rename work plan to work plan and
announcements... choose the employees... and a message to send them. the selected users should get a pop
up as soon as they open the app and a cut option to remove the popup") - a message from the admin to a
chosen set of employees, sent immediately, with one recipient row per chosen employee so dismissal can be
tracked per person.

Revision ID: f3a7c9e2d615
Revises: d2f8a4c6e913
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3a7c9e2d615'
down_revision = 'd2f8a4c6e913'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'announcements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'announcement_recipients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('announcement_id', sa.Integer(), nullable=False),
        sa.Column('user_code', sa.String(length=4), nullable=False),
        sa.Column('dismissed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['announcement_id'], ['announcements.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_code'], ['users.code'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('announcement_id', 'user_code', name='uq_announcement_recipients_user'),
    )
    with op.batch_alter_table('announcement_recipients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_announcement_recipients_announcement_id'), ['announcement_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_announcement_recipients_user_code'), ['user_code'], unique=False)


def downgrade():
    with op.batch_alter_table('announcement_recipients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_announcement_recipients_user_code'))
        batch_op.drop_index(batch_op.f('ix_announcement_recipients_announcement_id'))
    op.drop_table('announcement_recipients')
    op.drop_table('announcements')
