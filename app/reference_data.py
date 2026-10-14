"""Starting rows for the reference tables. The migration copies these values (a migration must not depend on app
code), and tests/test_reference_data.py checks that the two stay identical."""

# key, name, sees_all_records
ROLES = [
    ("admin", "Admin", True),
    ("sales_field", "Sales (field)", False),
    ("sales_office", "Sales (office)", False),  # sees every LEAD (visible_leads), but not sees_all's wider
                                                 # powers (everyone's attendance, project-manager assignment)
    ("project_manager", "Project manager", False),
    ("supervisor", "Site supervisor", False),
    ("accounts", "Accountant", True),
    # Site trades: they sign in only to check themselves in and out.
    ("welder", "Welder", False),
    ("fitter", "Fitter", False),
    ("helper", "Helper", False),
    ("alarm_technician", "Alarm technician", False),
    # Sees clients and projects, but only for the state(s) assigned to them (see UserState) - not sees_all,
    # which is everything everywhere. Listed last - this order must match each role's migration, since
    # tests/test_reference_data.py checks the seeded rows in insertion order.
    ("sub_admin", "Sub-admin", False),
    # Added for the full role-based access rollout (kohal's access matrix, 2026-10-14) - these four already
    # existed in prod, added on the fly from Add employee/Add user before this; the migration that adds
    # ROLE_MODULES access for them links to whichever key they already have there by name, not these ones,
    # so prod ends up with exactly one row per name either way (see b-series migration for the full story).
    ("office_assistant", "Office Assistant", True),
    ("alarm_tech_cum_site_supervisor", "Alarm Tech cum site supervisor", False),
    ("company_director", "Company Director", True),
    ("office_assistant_consultant", "Office Assistant cum client consultant", True),
]

# Which services each role can open. The admin can open everything, so it has no rows.
# Attendance is self check-in / check-out, so every role gets it, including supervisor and field sales
# who had nothing else to open before this.
ROLE_MODULES = {
    "sales_field": ["leads", "attendance"],
    "sales_office": ["leads", "attendance"],
    "project_manager": ["projects", "attendance"],
    "supervisor": ["projects", "attendance"],
    "accounts": ["clients", "projects", "inventory", "users", "workforce", "attendance"],
    "sub_admin": ["clients", "projects", "attendance"],
    "welder": ["attendance"],
    "fitter": ["attendance"],
    "helper": ["attendance"],
    "alarm_technician": ["attendance"],
    "office_assistant": ["clients", "projects", "inventory", "users", "workforce", "attendance"],
    "alarm_tech_cum_site_supervisor": ["projects", "attendance"],
    "company_director": ["clients", "projects", "inventory", "users", "workforce", "attendance", "leads"],
    "office_assistant_consultant": ["clients", "projects", "inventory", "users", "workforce", "attendance", "leads"],
}

# (role, module) pairs that can look but not touch - Accountant and Office Assistant can open Users & roles
# and Employee management to see them, but adding, editing or removing stays admin (and Company
# Director/Office Assistant cum client consultant, who aren't listed here, so get the normal full access).
# See RoleModule.write_access.
READONLY_ROLE_MODULES = {
    ("accounts", "users"), ("accounts", "workforce"),
    ("office_assistant", "users"), ("office_assistant", "workforce"),
}

# key, name, icon, path, sort_order
NEW_MODULES = [
    ("clients", "Clients", "clients", "/clients", 2),
    ("projects", "Projects", "projects", "/projects", 3),
    ("attendance", "Attendance", "attendance", "/attendance", 4),
    ("inventory", "Inventory", "material", "/inventory", 5),
    # Not a tile - see Module.in_nav. A permission gate for the Me hub's own "Manage" section instead
    # (_me_links.html), same pages the admin could already always open.
    ("users", "Users & roles", "user", "/users", 90),
    ("workforce", "Employee management", "manpower", "/workforce", 91),
]

NAV_HIDDEN_MODULES = {"users", "workforce"}

# Modules that are admin-only regardless of role_modules (check_module() refuses everyone else, even a
# role with its own row there). Inventory had no roles defined for it at first and lived here; now that
# several do (see ROLE_MODULES), it's an ordinary role-gated module instead - this set is empty, kept
# around for whenever a module needs to start admin-only again before its own roles are worked out.
ADMIN_ONLY_MODULES = set()

SITE_CATEGORIES = [
    "Hospital", "Nursing home", "Residential apartment", "Commercial complex",
    "School", "Educational institute", "Plant", "Industry", "Residential", "Commercial", "Multi dwelling unit",
    "Other",
]

SERVICES = [
    "Sprinklers setup", "Fire alarms", "Hydrant system and pump house", "Supply of extinguishers",
    "Gas suppression", "Electrical panel suppression", "Provisional NOC and compliance",
    "Final NOC and fire audits", "AMC", "Refilling of fire extinguishers",
    "Fire advisory", "Final NOC", "Renewal NOC", "Other",
]

# The first version's starting services that the list above replaces. They are switched off, not deleted,
# so leads that already use them keep their value.
OLD_SERVICES = ["Sprinklers", "Hydrant and pump room", "Extinguishers", "NOC and audits"]

PROJECT_STATUSES = ["planned", "running", "on_hold", "final_estimate_sent", "completed"]

# For picking which state(s) a sub-admin can see - fixed, not drawn from existing client/project data, so
# a state with no clients yet can still be assigned ahead of the first one landing there.
INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
