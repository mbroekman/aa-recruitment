"""Constants and reference datasets for the recruitment vetting engine."""

# Default hostile alliance / corporation keywords from 3Gods / INIT vetting guidelines
HOSTILE_ALLIANCE_TERMS = [
    "pandemic horde",
    "fraternity",
    "northern coalition",
    "nc.",
    "panfam",
    "winter coalition",
    "pl",
    "pandemic legion",
    "waaffles",
    "snuffed out",
    "snuff",
    "skill urself",
    "tactical narcotics",
    "tishu",
]

# Known friendly alliance keywords (Initiative / Imperium ecosystem)
FRIENDLY_ALLIANCE_TERMS = [
    "the initiative.",
    "initiative associates",
    "initiative mercenaries",
    "goonswarm federation",
    "the imperium",
    "imperium",
    "lawn",
    "tactical supremacy",
]

# External API endpoints
BLACKLIST_TABLE_URL = "https://zero.the-initiative.rocks/blacklist/tables/blacklist_table"
EVE_FORUM_SEARCH_URL = "https://forums.eveonline.com/search.json"
ZKILLBOARD_API_BASE = "https://zkillboard.com/api"
ESI_BASE_URL = "https://esi.evetech.net/latest"

# Kill activity analysis constants
SESSION_GAP_SECONDS = 7200  # 2 hours without kill/loss = separate fleet session
BREAK_MIN_DAYS = 90  # 3 months gap = inactivity break

# Severity weights and caps for risk score calculation (mirrors recommendation.lib.js)
SEVERITY_WEIGHTS = {
    "critical": 40,
    "high": 20,
    "medium": 10,
    "low": 2,
    "info": 0,
}

SEVERITY_CAPS = {
    "critical": 120,
    "high": 60,
    "medium": 30,
    "low": 10,
}

# Score boundaries
SCORE_GREEN_MAX = 9
SCORE_YELLOW_MAX = 29
SCORE_ORANGE_MAX = 79
# 80+ is RED
