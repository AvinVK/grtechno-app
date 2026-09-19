STAGES = ["New enquiry", "Site survey", "Quote sent", "Negotiation", "Won", "Lost"]
OPEN_STAGES = STAGES[:4]
WON = "Won"
LOST = "Lost"
CLOSED_STAGES = (WON, LOST)

# Starting lists. Edit them any time from the Settings page.
DEFAULT_SETTINGS = {
    "currency": "\u20b9",
    "country_code": "91",
    "services": "\n".join(
        [
            "Sprinklers",
            "Fire alarms",
            "Hydrant and pump room",
            "Extinguishers",
            "Gas suppression",
            "NOC and audits",
            "AMC",
        ]
    ),
    "sources": "\n".join(
        [
            "Referral",
            "Website",
            "Walk-in",
            "Cold call",
            "Tender / RFQ",
            "Repeat client",
            "Consultant / architect",
        ]
    ),
}
