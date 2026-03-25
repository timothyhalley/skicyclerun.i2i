"""POI selection logic — derive the HERE place and choose the best LINE 1 POI."""
from typing import Any, Dict, List, Optional

from .poi_constants import (
    HERE_FIRST_TYPES,
    LINE1_PRIORITY,
    LOW_VALUE_HERE_TYPES,
    NATURAL_NAME_HINTS,
)
from .poi_osm_queries import is_listing_noise


def derive_here_place(
    reverse_info: Dict[str, Any], nearby_pois: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Determine the place the photo is *actually at* before looking 'nearby'."""
    name = (reverse_info.get("name") or "").strip()
    approx = (reverse_info.get("approximation") or "").strip()
    category = (reverse_info.get("category") or "").strip().lower()
    place_type = (reverse_info.get("type") or "").strip().lower()
    here_haystack = f"{name.lower()} {approx.lower()} {category} {place_type}".strip()
    reverse_here_type = place_type or category or "place"

    if name and not is_listing_noise(name) and reverse_here_type not in LOW_VALUE_HERE_TYPES:
        return {"name": name, "type": reverse_here_type, "distance_m": 0.0, "source": "reverse"}

    if any(token in here_haystack for token in NATURAL_NAME_HINTS) and approx:
        return {
            "name": approx,
            "type": reverse_here_type or "natural_feature",
            "distance_m": 0.0,
            "source": "reverse",
        }

    if nearby_pois and nearby_pois[0].get("distance_m", 9999) <= 25:
        return {**nearby_pois[0], "source": "nearby_25m"}

    return None


def choose_line1_poi(
    here_place: Optional[Dict[str, Any]], nearby_pois: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Choose the best single POI for LINE 1 using priority + proximity scoring."""
    if here_place:
        here_type = (here_place.get("type") or "").lower()
        here_dist = float(here_place.get("distance_m") or 0)
        if (
            here_type in HERE_FIRST_TYPES
            and here_type not in LOW_VALUE_HERE_TYPES
            and here_dist <= 15
        ):
            return here_place

    nearby_scored = []
    for poi in nearby_pois:
        poi_type = (poi.get("type") or "").lower()
        dist = float(poi.get("distance_m") or 9999)
        if poi_type in LINE1_PRIORITY and dist <= 50:
            nearby_scored.append((LINE1_PRIORITY[poi_type], -dist, poi))
    if nearby_scored:
        nearby_scored.sort(reverse=True)
        return nearby_scored[0][2]

    if here_place:
        here_type = (here_place.get("type") or "").lower()
        if here_type not in LOW_VALUE_HERE_TYPES:
            return here_place

    nearby_scored_lenient = []
    for poi in nearby_pois:
        poi_type = (poi.get("type") or "").lower()
        dist = float(poi.get("distance_m") or 9999)
        nearby_scored_lenient.append((LINE1_PRIORITY.get(poi_type, 50), -dist, poi))
    if nearby_scored_lenient:
        nearby_scored_lenient.sort(reverse=True)
        return nearby_scored_lenient[0][2]

    return here_place
