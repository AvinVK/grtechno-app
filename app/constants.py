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

# The fixed installation checklist every project's Progress tab shows, in this order - same 9 stages for
# every project, not configurable per project (kohal, 2026-10-22). The admin sets a planned day count per
# stage and marks it done by hand (usually alongside the work photos); the day count is just a target shown
# to the client, nothing auto-advances from it. (key, label, note) - note is an optional one-line hint,
# shown under the label when present.
PROJECT_STAGES = [
    ("commencement", "Commencement", "Provision, estimate, building diagram"),
    ("riser_installation", "Riser installation", ""),
    ("sprinkler_installation", "Sprinkler pipeline installation", ""),
    ("alarm_cabling", "Alarm cabling", ""),
    ("fire_equipment_installation", "Fire equipment installation", ""),
    ("pump_installation", "Pump installation", ""),
    ("testing_commissioning", "Testing and commissioning", ""),
    ("portable_device_installation", "Portable device installation", "Fire extinguishers, fire buckets, etc."),
    ("handover", "Handover", ""),
]

# Why the current stage has stopped (kohal, 2026-10-22: "add pause button after each stage. if paused then
# whats the reason? payment not recieved, manpower shortage, material shortage") - "other" (with its own
# free-text note) is on top of the three given, so a stall with no better fit still records something.
PAUSE_REASONS = [
    ("payment_not_received", "Payment not received"),
    ("manpower_shortage", "Manpower shortage"),
    ("material_shortage", "Material shortage"),
    ("other", "Other"),
]

# Fallbacks for the two single-value rows in the settings table. The dropdown lists live in the
# services and lead_sources tables and are maintained directly in the database.
DEFAULT_SETTINGS = {
    "currency": "₹",
    "country_code": "91",
}
