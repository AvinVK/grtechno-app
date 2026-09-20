"""roles, site categories, lead checklist, clients and projects

Revision ID: a8d4f1c6e932
Revises: f6b2d9e13a70
Create Date: 2026-09-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a8d4f1c6e932'
down_revision = 'f6b2d9e13a70'
branch_labels = None
depends_on = None

# Copied from app/reference_data.py on purpose: a migration must not depend on app code.
ROLES = [
    ("admin", "Admin", True),
    ("sales_field", "Sales (field)", False),
    ("sales_office", "Sales (office)", False),
    ("project_manager", "Project manager", False),
    ("supervisor", "Site supervisor", False),
    ("accounts", "Accounts", True),
]
ROLE_MODULES = {
    "sales_field": ["leads"],
    "sales_office": ["leads"],
    "project_manager": ["clients", "projects"],
    "supervisor": [],
    "accounts": ["clients", "projects"],
}
NEW_MODULES = [
    ("clients", "Clients", "clients", "/clients", 2),
    ("projects", "Projects", "projects", "/projects", 3),
]
SITE_CATEGORIES = [
    "Hospital", "Nursing home", "Residential apartment", "Commercial complex",
    "School", "Educational institute", "Other",
]
SERVICES = [
    "Sprinklers setup", "Fire alarms", "Hydrant system and pump house", "Supply of extinguishers",
    "Gas suppression", "Electrical panel suppression", "Provisional NOC and compliance",
    "Final NOC and fire audits", "AMC", "Refilling of fire extinguishers", "Other",
]
OLD_SERVICES = ["Sprinklers", "Hydrant and pump room", "Extinguishers", "NOC and audits"]


def _named_table(name):
    return op.create_table(
        name,
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )


def upgrade():
    bind = op.get_bind()

    # ---- roles and what each role can open
    roles = op.create_table(
        'roles',
        sa.Column('key', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('sees_all', sa.Boolean(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    op.bulk_insert(roles, [{'key': k, 'name': n, 'sees_all': s} for k, n, s in ROLES])

    role_modules = op.create_table(
        'role_modules',
        sa.Column('role_key', sa.String(length=30), nullable=False),
        sa.Column('module_key', sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(['role_key'], ['roles.key'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['module_key'], ['modules.key'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_key', 'module_key'),
    )

    modules = sa.table('modules', sa.column('key'), sa.column('name'), sa.column('icon'), sa.column('path'),
                       sa.column('sort_order'), sa.column('is_active'), sa.column('admin_only'))
    op.bulk_insert(modules, [
        {'key': k, 'name': n, 'icon': i, 'path': p, 'sort_order': o, 'is_active': True, 'admin_only': False}
        for k, n, i, p, o in NEW_MODULES
    ])
    op.bulk_insert(role_modules, [{'role_key': r, 'module_key': m} for r, keys in ROLE_MODULES.items() for m in keys])

    # ---- everyone who already exists keeps working: the admin stays admin, others become field sales
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role_key', sa.String(length=30), nullable=True))
        batch_op.create_foreign_key('fk_users_role_key_roles', 'roles', ['role_key'], ['key'])
    bind.execute(sa.text("UPDATE users SET role_key = CASE WHEN is_admin = 1 THEN 'admin' ELSE 'sales_field' END"))

    # ---- site categories, and the work categories from the blueprint
    site_categories = _named_table('site_categories')
    op.bulk_insert(site_categories, [
        {'name': n, 'sort_order': i, 'is_active': True} for i, n in enumerate(SITE_CATEGORIES, start=1)
    ])
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('site_category', sa.String(length=60), server_default='', nullable=False))

    existing = {r[0] for r in bind.execute(sa.text("SELECT name FROM services")).fetchall()}
    for i, name in enumerate(SERVICES, start=1):
        if name in existing:
            bind.execute(sa.text("UPDATE services SET sort_order = :o, is_active = 1 WHERE name = :n"), {'o': i, 'n': name})
        else:
            bind.execute(sa.text("INSERT INTO services (name, sort_order, is_active) VALUES (:n, :o, 1)"), {'n': name, 'o': i})
    for name in OLD_SERVICES:
        bind.execute(sa.text("UPDATE services SET is_active = 0, sort_order = 100 WHERE name = :n"), {'n': name})

    # ---- lead checklist
    op.create_table(
        'lead_checklist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(length=200), nullable=False),
        sa.Column('done', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lead_checklist_items_lead_id', 'lead_checklist_items', ['lead_id'])

    # ---- clients and projects
    op.create_table(
        'clients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('contact_name', sa.String(length=120), server_default='', nullable=False),
        sa.Column('phone', sa.String(length=40), server_default='', nullable=False),
        sa.Column('email', sa.String(length=160), server_default='', nullable=False),
        sa.Column('site_category', sa.String(length=60), server_default='', nullable=False),
        sa.Column('pincode', sa.String(length=6), server_default='', nullable=False),
        sa.Column('state', sa.String(length=80), server_default='', nullable=False),
        sa.Column('district', sa.String(length=80), server_default='', nullable=False),
        sa.Column('city', sa.String(length=120), server_default='', nullable=False),
        sa.Column('address', sa.String(length=400), server_default='', nullable=False),
        sa.Column('notes', sa.Text(), server_default='', nullable=False),
        sa.Column('owner_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_clients_owner_code', 'clients', ['owner_code'])

    op.create_table(
        'projects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('work_category', sa.String(length=120), server_default='', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='planned', nullable=False),
        sa.Column('site_pincode', sa.String(length=6), server_default='', nullable=False),
        sa.Column('site_state', sa.String(length=80), server_default='', nullable=False),
        sa.Column('site_district', sa.String(length=80), server_default='', nullable=False),
        sa.Column('site_city', sa.String(length=120), server_default='', nullable=False),
        sa.Column('site_address', sa.String(length=400), server_default='', nullable=False),
        sa.Column('work_order_no', sa.String(length=60), server_default='', nullable=False),
        sa.Column('work_order_date', sa.Date(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('completion_days', sa.Integer(), nullable=True),
        sa.Column('estimated_amount', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('discount_amount', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('payment_terms', sa.Text(), server_default='', nullable=False),
        sa.Column('special_terms', sa.Text(), server_default='', nullable=False),
        sa.Column('manager_code', sa.String(length=4), nullable=True),
        sa.Column('owner_code', sa.String(length=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id']),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['manager_code'], ['users.code'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['owner_code'], ['users.code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lead_id'),
    )
    op.create_index('ix_projects_client_id', 'projects', ['client_id'])
    op.create_index('ix_projects_status', 'projects', ['status'])
    op.create_index('ix_projects_manager_code', 'projects', ['manager_code'])
    op.create_index('ix_projects_owner_code', 'projects', ['owner_code'])

    op.create_table(
        'project_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_project_payments_project_id', 'project_payments', ['project_id'])


def downgrade():
    op.drop_table('project_payments')
    op.drop_table('projects')
    op.drop_table('clients')
    op.drop_table('lead_checklist_items')
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_column('site_category')
    op.drop_table('site_categories')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_role_key_roles', type_='foreignkey')
        batch_op.drop_column('role_key')
    op.get_bind().execute(sa.text("DELETE FROM modules WHERE key IN ('clients', 'projects')"))
    op.drop_table('role_modules')
    op.drop_table('roles')
