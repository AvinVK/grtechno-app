STAGES = ["New enquiry", "Site survey", "Quote sent", "Negotiation", "Won", "Lost"]
OPEN_STAGES = STAGES[:4]
WON = "Won"
LOST = "Lost"
CLOSED_STAGES = (WON, LOST)

# Fallbacks for the two single-value rows in the settings table. The dropdown lists live in the
# services and lead_sources tables and are maintained directly in the database.
DEFAULT_SETTINGS = {
    "currency": "₹",
    "country_code": "91",
}
