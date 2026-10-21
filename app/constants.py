STAGES = ["New enquiry", "Site survey", "Quote sent", "Negotiation", "Work order & advance", "Won", "Lost"]
OPEN_STAGES = STAGES[:5]
WON = "Won"
LOST = "Lost"
CLOSED_STAGES = (WON, LOST)

# How a payment (the advance, or a project's own payment steps) actually came in.
PAYMENT_MODES = ["Cash", "Cheque", "Bank transfer", "UPI", "Other"]

# Who earns commission on a project's negotiated amount (kohal, 2026-10-18) - a role the admin already
# added on prod via Users & roles, same as any custom role; this is just the one key everything else
# (app/projects.py's commission entries, app/workers.py's "Commission earned" stat) checks against.
COMMISSION_ROLE_KEY = "project_manager_chandrapur"

# The paperwork that must be on file before a project can close, once the final on-site measurement is in
# (kohal, 2026-10-21: "need to mandatorily upload these 3 things once measure done = true. final estimate,
# work completion certi, final invoice mandatory upload"). Order is display order.
PROJECT_DOCUMENT_TYPES = [
    ("final_estimate", "Final estimate"),
    ("completion_certificate", "Work completion certificate"),
    ("final_invoice", "Final invoice"),
]

# This role also sees every project in this district specifically (kohal, 2026-10-18: "alocate chandrapur
# region projects... to project manager chandrapur role"), on top of whatever it manages elsewhere - not
# every project company-wide the way the plain project_manager role does (see auth.visible_projects).
CHANDRAPUR_DISTRICT = "Chandrapur"

# Fallbacks for the two single-value rows in the settings table. The dropdown lists live in the
# services and lead_sources tables and are maintained directly in the database.
DEFAULT_SETTINGS = {
    "currency": "₹",
    "country_code": "91",
}
