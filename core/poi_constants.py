"""All POI classification constants — type sets, priority tables, province/state maps."""

# ---------------------------------------------------------------------------
# Types to suppress from watermark output entirely
# ---------------------------------------------------------------------------

LOW_VALUE_TYPES = {
    "parking", "bench", "waste_basket", "waste_disposal", "bicycle_parking",
    "bus_stop", "atm", "bank", "fuel", "car_repair", "car_wash", "toilets",
    "public_bookcase", "vending_machine", "post_box", "post_office", "pharmacy"
}

LISTING_NOISE_TOKENS = {
    "monthly rates", "rates negotiable", "luxury condo", "corner-suite", "make yourself at home",
    "sq.ft", "pets ok", "pet friendly", "airbnb", "vrbo", "book now", "short term rental"
}

NATURAL_NAME_HINTS = {
    "park", "beach", "trail", "trailhead", "mountain", "peak", "ridge", "hill",
    "falls", "waterfall", "landing", "lookout", "viewpoint", "lake", "bay", "reserve"
}

LOW_VALUE_HERE_TYPES = {
    "parking", "parking_lot", "parking_entrance",
    "street", "road", "highway", "residential",
    "living_street", "primary", "secondary", "tertiary",
    "unclassified", "service", "postcode"
}

# ---------------------------------------------------------------------------
# LINE 1 selection priorities (higher = preferred)
# ---------------------------------------------------------------------------

LINE1_PRIORITY = {
    "artwork": 130,       # Art always prevails over commercial and natural POIs
    "restaurant": 120,
    "cafe": 115,
    "lodging": 110,
    "hotel": 110,
    "resort": 108,
    "beach": 105,
    "water": 104,
    "bay": 104,
    "park": 100,
    "protected_area": 100,
    "footway": 99,
    "path": 99,
    "trailhead": 98,
    "peak": 95,
    "mountain": 95,
    "waterfall": 95,
    "museum": 90,
    "gallery": 90,
    "attraction": 88,
    "natural_feature": 85,
}

# POI types that get shown with direct distance/direction on LINE 1
DIRECT_POI_LINE1_TYPES = {
    "restaurant", "cafe", "lodging", "hotel", "resort",
    "museum", "gallery", "attraction", "artwork"
}

# POI types that take priority when you are physically *at* the feature
HERE_FIRST_TYPES = {
    "artwork",
    "attraction", "museum", "gallery",
    "park", "protected_area", "beach", "water", "bay",
    "mountain", "peak", "natural_feature", "trailhead", "path", "footway"
}

TRAIL_TYPES = {"footway", "path", "trailhead"}
AREA_CONTEXT_TYPES = {"park", "protected_area", "mountain", "peak", "natural_feature"}
MAX_NATURAL_CONTEXT_DISTANCE_M = 1500

# ---------------------------------------------------------------------------
# Province / state abbreviation maps
# ---------------------------------------------------------------------------

CA_PROVINCES = {
    "Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB", "New Brunswick": "NB",
    "Newfoundland and Labrador": "NL", "Northwest Territories": "NT", "Nova Scotia": "NS",
    "Nunavut": "NU", "Ontario": "ON", "Prince Edward Island": "PE", "Quebec": "QC",
    "Saskatchewan": "SK", "Yukon": "YT"
}

US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO",
    "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "District of Columbia": "DC"
}
