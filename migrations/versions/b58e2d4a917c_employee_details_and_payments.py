"""Employee details (age, qualification, phone, joining date, wages, PF/ESIC, ...) and a salary/wages
payment log, mirroring project payments

Revision ID: b58e2d4a917c
Revises: a3c7f1e9b204
Create Date: 2026-10-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b58e2d4a917c'
down_revision = 'a3c7f1e9b204'
branch_labels = None
depends_on = None


def _columns(conn, table):
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


NEW_WORKER_COLUMNS = [
    ('age', sa.Integer(), {}),
    ('qualification', sa.String(length=160), {'server_default': ''}),
    ('experience', sa.String(length=200), {'server_default': ''}),
    ('skills', sa.String(length=400), {'server_default': ''}),
    ('phone', sa.Text(), {}),
    ('joining_date', sa.Date(), {}),
    ('employment_type', sa.String(length=20), {'server_default': ''}),
    ('wage_amount', sa.Numeric(14, 2), {}),
    ('pf_number', sa.Text(), {}),
    ('esic_number', sa.Text(), {}),
    ('reference', sa.String(length=200), {'server_default': ''}),
]


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_workers"))
    existing = _columns(conn, 'workers')
    with op.batch_alter_table('workers', schema=None) as batch_op:
        for name, col_type, extra in NEW_WORKER_COLUMNS:
            if name not in existing:
                nullable = 'server_default' not in extra
                batch_op.add_column(sa.Column(name, col_type, nullable=nullable, **extra))

    if not conn.dialect.has_table(conn, 'worker_payments'):
        op.create_table(
            'worker_payments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('worker_id', sa.Integer(), nullable=False),
            sa.Column('label', sa.String(length=120), nullable=False),
            sa.Column('amount', sa.Numeric(14, 2), server_default='0', nullable=False),
            sa.Column('due_date', sa.Date(), nullable=True),
            sa.Column('position', sa.Integer(), server_default='0', nullable=False),
            sa.Column('mode', sa.String(length=40), server_default='', nullable=False),
            sa.Column('paid_date', sa.Date(), nullable=True),
            sa.Column('comments', sa.Text(), server_default='', nullable=False),
            sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_worker_payments_worker_id', 'worker_payments', ['worker_id'])


def downgrade():
    op.drop_index('ix_worker_payments_worker_id', table_name='worker_payments')
    op.drop_table('worker_payments')
    with op.batch_alter_table('workers', schema=None) as batch_op:
        for name, _col_type, _extra in reversed(NEW_WORKER_COLUMNS):
            batch_op.drop_column(name)
