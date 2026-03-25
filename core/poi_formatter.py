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


# ---------------------------------------------------------------------------
# Two-line watermark assembly
# ---------------------------------------------------------------------------

def build_two_line_watermark(
    reverse_info: Dict[str, Any],
    here_place: Optional[Dict[str, Any]],
    nearby_pois: List[Dict[str, Any]],
    known_hint: Optional[Dict[str, Any]] = None,
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
    if known_hint and known_hint.get("line1"):
        line1 = known_hint["line1"]
        line2 = known_hint.get("line2") or format_line2(reverse_info)
        return line1, line2

    best_line1_poi = choose_line1_poi(here_place, nearby_pois)
    approx = (reverse_info.get("approximation") or "Unknown location").strip()

    if best_line1_poi:
        poi_name = (best_line1_poi.get("name") or "").strip()
        poi_type = (best_line1_poi.get("type") or "").lower()
        dist = best_line1_poi.get("distance_m")
        direction = best_line1_poi.get("bearing_cardinal")

        # --- Artwork: show with distance then pull in nearest notable landmark ---
        if poi_name and poi_type == "artwork":
            art_part = (
                f"{poi_name} ({dist:.0f}m {direction})"
                if dist not in (None, 0) and direction
                else (f"{poi_name} ({dist:.0f}m)" if dist not in (None, 0) else poi_name)
            )
            ctx_candidates = []
            for candidate in nearby_pois:
                c_name = (candidate.get("name") or "").strip()
                c_type = (candidate.get("type") or "").lower()
                c_dist = float(candidate.get("distance_m") or 9999)
                if not c_name or c_name == poi_name or c_type == "artwork":
                    continue
                if c_type in LINE1_PRIORITY and c_dist <= 150:
                    ctx_candidates.append((LINE1_PRIORITY[c_type], -c_dist, candidate))
            if ctx_candidates:
                ctx_candidates.sort(reverse=True)
                ctx = ctx_candidates[0][2]
                ctx_name = (ctx.get("name") or "").strip()
                ctx_dist = ctx.get("distance_m")
                ctx_dir = ctx.get("bearing_cardinal")
                if ctx_dist not in (None, 0) and ctx_dir:
                    line1 = f"{art_part} near {ctx_name} ({ctx_dist:.0f}m {ctx_dir})"
                else:
                    line1 = f"{art_part} near {ctx_name}"
            else:
                line1 = art_part
            return line1, format_line2(reverse_info)

        # --- Trail: resolve to a larger area context when available ---
        if poi_name and poi_type in TRAIL_TYPES:
            area_candidates = []
            for candidate in nearby_pois:
                c_name = (candidate.get("name") or "").strip()
                c_type = (candidate.get("type") or "").lower()
                c_dist = float(candidate.get("distance_m") or 9999)
                if not c_name or c_name == poi_name:
                    continue
                if c_type in AREA_CONTEXT_TYPES and c_dist <= MAX_NATURAL_CONTEXT_DISTANCE_M:
                    area_candidates.append((c_dist, candidate))
            if area_candidates:
                area_candidates.sort(key=lambda x: x[0])
                area_name = area_candidates[0][1].get("name")
                if area_name:
                    return f"{poi_name} on {area_name}", format_line2(reverse_info)

        # --- Direct named POI with distance/direction ---
        if poi_name and dist not in (None, 0) and poi_type in DIRECT_POI_LINE1_TYPES:
            line1 = f"{poi_name} ({dist:.0f}m {direction})" if direction else f"{poi_name} ({dist:.0f}m)"

        elif poi_name and here_place:
            here_name = (here_place.get("name") or "").strip()
            here_type = (here_place.get("type") or "").lower()
            if here_name and poi_name and here_name != poi_name and here_type in LOW_VALUE_HERE_TYPES:
                if dist is not None and direction:
                    line1 = f"{here_name} near {poi_name} ({dist:.0f}m {direction})"
                else:
                    line1 = f"{here_name} near {poi_name}"
            else:
                line1 = poi_name

        elif poi_name:
            line1 = poi_name
        else:
            line1 = approx
    else:
        line1 = approx

    return line1, format_line2(reverse_info)
