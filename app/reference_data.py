"""Starting rows for the reference tables. The migration copies these values (a migration must not depend on app
code), and tests/test_reference_data.py checks that the two stay identical."""

# key, name, sees_all_records
ROLES = [
    ("admin", "Admin", True),
    ("sales_field", "Sales (field)", False),
    ("sales_office", "Sales (office)", False),
    ("project_manager", "Project manager", False),
    ("supervisor", "Site supervisor", False),
    ("accounts", "Accounts", True),
]

# Which services each role can open. The admin can open everything, so it has no rows.
# Attendance is self check-in / check-out, so every role gets it, including supervisor and field sales
# who had nothing else to open before this.
ROLE_MODULES = {
    "sales_field": ["leads", "attendance"],
    "sales_office": ["leads", "attendance"],
    "project_manager": ["clients", "projects", "attendance"],
    "supervisor": ["attendance"],
    "accounts": ["clients", "projects", "attendance"],
}

# key, name, icon, path, sort_order
NEW_MODULES = [
    ("clients", "Clients", "clients", "/clients", 2),
    ("projects", "Projects", "projects", "/projects", 3),
    ("attendance", "Attendance", "attendance", "/attendance", 4),
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

# The first version's starting services that the list above replaces. They are switched off, not deleted,
# so leads that already use them keep their value.
OLD_SERVICES = ["Sprinklers", "Hydrant and pump room", "Extinguishers", "NOC and audits"]

PROJECT_STATUSES = ["planned", "running", "on_hold", "completed"]
