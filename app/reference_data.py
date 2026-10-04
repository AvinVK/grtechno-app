"""Starting rows for the reference tables. The migration copies these values (a migration must not depend on app
code), and tests/test_reference_data.py checks that the two stay identical."""

# key, name, sees_all_records
ROLES = [
    ("admin", "Admin", True),
    ("sales_field", "Sales (field)", False),
    ("sales_office", "Sales (office)", False),
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
    "sub_admin": ["clients", "projects", "attendance"],
    "welder": ["attendance"],
    "fitter": ["attendance"],
    "helper": ["attendance"],
    "alarm_technician": ["attendance"],
}

# key, name, icon, path, sort_order
NEW_MODULES = [
    ("clients", "Clients", "clients", "/clients", 2),
    ("projects", "Projects", "projects", "/projects", 3),
    ("attendance", "Attendance", "attendance", "/attendance", 4),
]

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
