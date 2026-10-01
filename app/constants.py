STAGES = ["New enquiry", "Site survey", "Quote sent", "Negotiation", "Work order & advance", "Won", "Lost"]
OPEN_STAGES = STAGES[:5]
WON = "Won"
LOST = "Lost"
CLOSED_STAGES = (WON, LOST)

# How a payment (the advance, or a project's own payment steps) actually came in.
PAYMENT_MODES = ["Cash", "Cheque", "Bank transfer", "UPI", "Other"]

# Fallbacks for the two single-value rows in the settings table. The dropdown lists live in the
# services and lead_sources tables and are maintained directly in the database.
DEFAULT_SETTINGS = {
    "currency": "₹",
    "country_code": "91",
}
