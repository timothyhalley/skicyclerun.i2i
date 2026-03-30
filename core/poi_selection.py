"""POI selection logic — derive the HERE place and choose the best LINE 1 POI."""
from typing import Any, Dict, List, Optional

from .poi_constants import (
    HERE_FIRST_TYPES,
    LINE1_PRIORITY,
    LOW_VALUE_HERE_TYPES,
    NATURAL_NAME_HINTS,
)
from .poi_osm_queries import is_listing_noise


WATERMARK_ALLOWED_CATEGORIES = {
    "restaurant",
    "cafe",
    "bar",
    "hotel",
    "view",
    "landmark",
    "museum",
    "shop",
}

# Lower value means higher priority in tie-break sorting.
WATERMARK_CATEGORY_PRIORITY = {
    "restaurant": 0,
    "cafe": 1,
    "bar": 2,
    "hotel": 3,
    "view": 4,
    "landmark": 5,
    "museum": 6,
    "shop": 7,
}


def _normalize_watermark_category(poi: Dict[str, Any]) -> Optional[str]:
    """Map provider-specific POI type/category labels into watermark buckets."""
    raw_category = (poi.get("category") or "").strip().lower()
    raw_type = (poi.get("type") or "").strip().lower()
    token = raw_category or raw_type

    if token in {"restaurant"}:
        return "restaurant"
    if token in {"cafe", "coffee_shop"}:
        return "cafe"
    if token in {"bar", "pub", "brewery"}:
        return "bar"
    if token in {"hotel", "lodging", "resort"}:
        return "hotel"
    if token in {"viewpoint", "view"}:
        return "view"
    if token in {"museum"}:
        return "museum"
    if token in {"shop", "store", "marketplace", "mall"}:
        return "shop"

    # Treat culturally/visually meaningful anchors as "landmark".
    if token in {
        "landmark",
        "attraction",
        "artwork",
        "monument",
        "memorial",
        "historic",
        "historic_site",
        "viewpoint",
        "gallery",
    }:
        return "landmark"

    return None


def select_watermark_pois(
    nearby_pois: List[Dict[str, Any]],
    max_distance_m: float = 75.0,
    limit: int = 3,
    allowed_categories: Optional[List[str]] = None,
    category_priority: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """Filter/sort nearby POIs for readable watermark context.

    Rules:
    - name must be present
    - distance_m <= max_distance_m
    - normalized category in WATERMARK_ALLOWED_CATEGORIES
    - sort by (distance asc, category priority asc)
    - return top `limit`
    """
    selected = []
    effective_allowed = {
        str(cat).strip().lower() for cat in (allowed_categories or WATERMARK_ALLOWED_CATEGORIES)
    }
    effective_priority = {
        str(k).strip().lower(): int(v)
        for k, v in (category_priority or WATERMARK_CATEGORY_PRIORITY).items()
    }

    for poi in nearby_pois or []:
        name = (poi.get("name") or "").strip()
        if not name:
            continue

        try:
            dist = float(poi.get("distance_m"))
        except (TypeError, ValueError):
            continue

        if dist > max_distance_m:
            continue

        wm_category = _normalize_watermark_category(poi)
        if wm_category not in effective_allowed:
            continue

        selected.append((dist, effective_priority.get(wm_category, 999), poi))

    selected.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in selected[: max(0, int(limit))]]


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
