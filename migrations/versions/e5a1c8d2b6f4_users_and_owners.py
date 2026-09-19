"""users table and lead owners

Revision ID: e5a1c8d2b6f4
Revises: d4e9b7c0a1f3
Create Date: 2026-09-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5a1c8d2b6f4'
down_revision = 'd4e9b7c0a1f3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('code', sa.String(length=4), nullable=False),
        sa.Column('userid', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('is_admin', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=True),
        sa.Column('setup_code_hash', sa.String(length=255), nullable=True),
        sa.Column('setup_code_expires', sa.DateTime(), nullable=True),
        sa.Column('failed_attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('code'),
        sa.UniqueConstraint('userid'),
    )
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_code', sa.String(length=4), nullable=True))
        batch_op.create_index(batch_op.f('ix_leads_owner_code'), ['owner_code'], unique=False)
        batch_op.create_foreign_key('fk_leads_owner_code_users', 'users', ['owner_code'], ['code'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_constraint('fk_leads_owner_code_users', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_leads_owner_code'))
        batch_op.drop_column('owner_code')
    op.drop_table('users')
