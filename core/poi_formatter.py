"""Watermark text formatters — LINE 1, LINE 2, bilingual merging, two-line assembly."""
from typing import Any, Dict, List, Optional, Tuple

from .poi_constants import (
    AREA_CONTEXT_TYPES,
    CA_PROVINCES,
    DIRECT_POI_LINE1_TYPES,
    LINE1_PRIORITY,
    LOW_VALUE_HERE_TYPES,
    MAX_NATURAL_CONTEXT_DISTANCE_M,
    TRAIL_TYPES,
    US_STATES,
)
from .poi_selection import choose_line1_poi


# ---------------------------------------------------------------------------
# Debug helper
# ---------------------------------------------------------------------------

def format_poi_inline(poi: Dict[str, Any]) -> str:
    """Compact single-line representation used for terminal debug output."""
    if not poi:
        return "none"
    dist = poi.get("distance_m")
    direction = poi.get("bearing_cardinal")
    poi_type = poi.get("type") or "?"
    if dist is None or dist == 0:
        return f"{poi['name']} [{poi_type}]"
    return f"{poi['name']} [{poi_type}] ({dist:.0f}m {direction})"


# ---------------------------------------------------------------------------
# LINE 2 — city/province/country string
# ---------------------------------------------------------------------------

def format_line2(reverse_info: Dict[str, Any]) -> str:
    """Build 'City, Province' or 'City, Country' for watermark LINE 2."""
    address = reverse_info.get("address", {})
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("hamlet")
        or address.get("suburb")
    )
    state = address.get("state") or ""
    country = address.get("country") or ""
    country_code = (address.get("country_code") or "").upper()

    if country_code == "CA":
        province = CA_PROVINCES.get(state, state)
        if city and province:
            return f"{city}, {province}"
        return city or province or country or "Unknown Location"

    if country_code == "US":
        state_code = US_STATES.get(state, state)
        if city and state_code:
            return f"{city}, {state_code}"
        return city or state_code or country or "Unknown Location"

    if city and country:
        return f"{city}, {country}"
    return city or country or reverse_info.get("approximation") or "Unknown Location"


# ---------------------------------------------------------------------------
# Bilingual helpers
# ---------------------------------------------------------------------------

def _normalize_for_compare(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def format_bilingual(native_text: str, english_text: str) -> str:
    """Return 'Native (English)' when texts differ, otherwise just native."""
    native = (native_text or "").strip()
    english = (english_text or "").strip()
    if not native:
        return english
    if not english:
        return native
    if _normalize_for_compare(native) == _normalize_for_compare(english):
        return native
    return f"{native} ({english})"


def get_feature_english_name(feature: Optional[Dict[str, Any]]) -> str:
    """Extract the English name from OSM tags, trying several tag keys."""
    if not feature:
        return ""
    tags = feature.get("tags") or {}
    for key in ("name:en", "int_name", "official_name:en", "alt_name:en"):
        value = (tags.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalize_anchor_type(poi: Dict[str, Any]) -> str:
    """Map POI type/category aliases into stable anchor buckets."""
    raw_type = (poi.get("type") or "").strip().lower()
    raw_category = (poi.get("category") or "").strip().lower()
    token = raw_type or raw_category

    if token in {"restaurant"}:
        return "restaurant"
    if token in {"cafe", "coffee_shop"}:
        return "cafe"
    if token in {"hotel", "lodging", "resort"}:
        return "hotel"
    if token in {"viewpoint"}:
        return "view"
    if token in {"trailhead", "path", "footway", "trail"}:
        return "trailhead"
    if token in {"park", "protected_area", "national_park"}:
        return "park"
    if token in {"mountain", "peak"}:
        return "peak"
    if token in {"waterfall", "falls"}:
        return "waterfall"
    if token in {"memorial"}:
        return "memorial"
    if token in {"attraction"}:
        return "attraction"
    if token in {"monument", "historic", "historic_site", "artwork", "gallery", "museum"}:
        return "monument"
    if token in {"forest", "wood", "woodland"}:
        return "forest"
    if token in {"street", "road", "highway", "living_street", "residential", "secondary", "pedestrian"}:
        return "street"
    return token


def _pick_context_anchor(
    reverse_info: Dict[str, Any],
    here_place: Optional[Dict[str, Any]],
    nearby_pois: List[Dict[str, Any]],
    known_hint: Optional[Dict[str, Any]],
    context_types: Optional[List[str]] = None,
) -> str:
    """Pick left side of LINE 1: hint/street/landscape/historic context."""
    if known_hint:
        hinted = (known_hint.get("line1") or known_hint.get("name") or "").strip()
        if hinted:
            return hinted

    allowed_context_types = {
        str(v).strip().lower()
        for v in (
            context_types
            or [
                "street", "monument", "park", "trailhead", "beach", "peak",
                "waterfall", "memorial", "attraction", "forest", "national_park",
            ]
        )
    }

    # Prefer the here place when it looks meaningful.
    if here_place:
        here_name = (here_place.get("name") or "").strip()
        here_type = _normalize_anchor_type(here_place)
        if here_name and here_type in allowed_context_types:
            return here_name

    # Next: nearest contextual POI.
    context_candidates = []
    for poi in nearby_pois:
        name = (poi.get("name") or "").strip()
        if not name:
            continue
        anchor_type = _normalize_anchor_type(poi)
        if anchor_type not in allowed_context_types:
            continue
        dist = float(poi.get("distance_m") or 9999)
        context_candidates.append((dist, name))

    if context_candidates:
        context_candidates.sort(key=lambda x: x[0])
        return context_candidates[0][1]

    # Final fallback: reverse approximation.
    approx = (reverse_info.get("approximation") or "").strip()
    if approx:
        return approx

    return "Unknown location"


def _pick_experience_anchor(
    nearby_pois: List[Dict[str, Any]],
    context_anchor: str,
    experience_types_priority: Optional[List[str]] = None,
) -> str:
    """Pick right side of LINE 1: cafe/restaurant/hotel/view/historic POI."""
    if experience_types_priority:
        priority = {
            str(v).strip().lower(): idx
            for idx, v in enumerate(experience_types_priority)
            if str(v).strip()
        }
    else:
        priority = {
            "restaurant": 0,
            "cafe": 1,
            "hotel": 2,
            "view": 3,
            "monument": 4,
            "memorial": 5,
            "attraction": 6,
        }

    candidates = []
    for poi in nearby_pois:
        name = (poi.get("name") or "").strip()
        if not name or name == context_anchor:
            continue
        anchor_type = _normalize_anchor_type(poi)
        if anchor_type not in priority:
            continue
        dist = float(poi.get("distance_m") or 9999)
        candidates.append((dist, priority[anchor_type], name))

    if not candidates:
        return ""

    # Sort by distance first, then semantic priority.
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


def _build_rule_line1(
    reverse_info: Dict[str, Any],
    here_place: Optional[Dict[str, Any]],
    nearby_pois: List[Dict[str, Any]],
    known_hint: Optional[Dict[str, Any]],
    line1_rule_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the requested LINE 1 rule: {context} · {experience}."""
    rule_cfg = line1_rule_config or {}
    separator = str(rule_cfg.get("separator", " · "))
    context_types = rule_cfg.get("context_types")
    experience_types_priority = rule_cfg.get("experience_types_priority")

    context_anchor = _pick_context_anchor(
        reverse_info,
        here_place,
        nearby_pois,
        known_hint,
        context_types=context_types,
    )
    experience_anchor = _pick_experience_anchor(
        nearby_pois,
        context_anchor,
        experience_types_priority=experience_types_priority,
    )
    if experience_anchor:
        return f"{context_anchor}{separator}{experience_anchor}"
    return context_anchor


# ---------------------------------------------------------------------------
# Two-line watermark assembly
# ---------------------------------------------------------------------------

def build_two_line_watermark(
    reverse_info: Dict[str, Any],
    here_place: Optional[Dict[str, Any]],
    nearby_pois: List[Dict[str, Any]],
    known_hint: Optional[Dict[str, Any]] = None,
    line1_rule_config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Assemble (line1, line2) from here-place, nearby POIs, and optional hint.

    Priority chain:
    1. Known location hint override.
    2. Artwork POI with nearest notable landmark as context.
    3. Trail on area-context feature.
    4. Direct named POI with distance / direction.
    5. Composite here-place + nearby POI phrase.
    6. HERE place name alone.
    7. Reverse-geocode approximation.
    """
    line1 = _build_rule_line1(
        reverse_info,
        here_place,
        nearby_pois,
        known_hint,
        line1_rule_config=line1_rule_config,
    )
    line2 = (known_hint or {}).get("line2") or format_line2(reverse_info)
    return line1, line2
