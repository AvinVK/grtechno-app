"""cash purchase tracking (kohal, 2026-10-21: "admin gives money to employees to purchase a stock or fuel
etc, we need to track that... cash given by admin -> purchase recorded by employee and approved by admin
... once approved by admin then balance gets deducted") - three tables, same shape as fooding's own
(FoodingAccount/FoodingEntry) but without its automatic daily-deduction columns, plus the pending/approved/
rejected request lifecycle borrowed from MaterialMovement. See app/models.py's CashAccount/CashTopup/
CashPurchase for the full story.

Revision ID: fe3d625d936b
Revises: d4a6e8c2f731
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'fe3d625d936b'
down_revision = 'd4a6e8c2f731'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cash_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('given_total', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('spent_total', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('worker_id'),
    )
    with op.batch_alter_table('cash_accounts', schema=None) as batch_op:
        batch_op.create_index('ix_cash_accounts_worker_id', ['worker_id'])

    op.create_table(
        'cash_topups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('payment_mode', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=200), server_default='', nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['cash_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('cash_topups', schema=None) as batch_op:
        batch_op.create_index('ix_cash_topups_account_id', ['account_id'])

    op.create_table(
        'cash_purchases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('material_name', sa.String(length=120), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('unit', sa.String(length=20), server_default='', nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('supplier', sa.String(length=120), server_default='', nullable=False),
        sa.Column('note', sa.String(length=500), server_default='', nullable=False),
        sa.Column('bill_filename', sa.String(length=80), nullable=True),
        sa.Column('created_by_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=10), server_default='pending', nullable=False),
        sa.Column('approved_by_code', sa.String(length=4), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['cash_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approved_by_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('cash_purchases', schema=None) as batch_op:
        batch_op.create_index('ix_cash_purchases_account_id', ['account_id'])


def downgrade():
    with op.batch_alter_table('cash_purchases', schema=None) as batch_op:
        batch_op.drop_index('ix_cash_purchases_account_id')
    op.drop_table('cash_purchases')

    with op.batch_alter_table('cash_topups', schema=None) as batch_op:
        batch_op.drop_index('ix_cash_topups_account_id')
    op.drop_table('cash_topups')

    with op.batch_alter_table('cash_accounts', schema=None) as batch_op:
        batch_op.drop_index('ix_cash_accounts_worker_id')
    op.drop_table('cash_accounts')
