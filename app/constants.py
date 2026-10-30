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

# The two things an adhoc client can buy (kohal, 2026-10-30: "in adhoc client, there will only be supply of
# extinguisher and refilling of extinguisher as service. single choice"): the key the form uses, the label it
# shows, and the name of the Service row (see Service in models.py) the adhoc project is filed under.
# An adhoc project is not "running": it waits Unbilled until the stock for its items has been issued from
# inventory, then it is Billed and closed (kohal, 2026-10-31).
ADHOC_STATUSES = ["unbilled", "billed"]

ADHOC_SERVICES = [
    ("supply", "Supply of FE and Retail sale", "Supply of extinguishers"),
    ("refilling", "Refilling of FE", "Refilling of fire extinguishers"),
]

# What a kilometre of an employee's own-vehicle riding is paid, in rupees (kohal, 2026-10-27: "everyday
# petrol amount = diff in kilometer *4") - see models.PetrolEntry.
PETROL_RATE_PER_KM = 4

# Papers a project can have on file at any time, none of them needed to close it (kohal, 2026-10-26: "work
# order (BOQ) and purchase order upload option for existing projects") - stored in the same project_documents
# table as the closing documents above, but kept out of PROJECT_DOCUMENT_TYPES so they never block closing.
PROJECT_ATTACHMENT_TYPES = [
    ("work_order_boq", "Work order (BOQ)"),
    ("purchase_order", "Purchase order"),
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
