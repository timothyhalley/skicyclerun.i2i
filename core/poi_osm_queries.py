"""Nominatim reverse-geocode + Overpass nearby-POI queries."""
from typing import Any, Dict, List, Optional

import requests

from .poi_constants import (
    CA_PROVINCES,
    LISTING_NOISE_TOKENS,
    LOW_VALUE_TYPES,
    MAX_NATURAL_CONTEXT_DISTANCE_M,
    US_STATES,
)
from .poi_overpass import extract_features, query_osm

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "SkiCycleRun-POI-Watermark/1.0"


# ---------------------------------------------------------------------------
# Nominatim reverse geocode
# ---------------------------------------------------------------------------

def reverse_lookup_free(
    lat: float, lon: float, accept_language: Optional[str] = None
) -> Dict[str, Any]:
    """Reverse-geocode via Nominatim. Returns a normalised address dict."""
    params: Dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "addressdetails": 1,
        "namedetails": 1,
        "extratags": 1,
        "zoom": 18,
    }
    if accept_language:
        params["accept-language"] = accept_language

    headers = {"User-Agent": USER_AGENT}
    response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    data = response.json()

    address = data.get("address", {})
    namedetails = data.get("namedetails") or {}
    name = namedetails.get("name") or data.get("name")

    approx = (
        name
        or address.get("road")
        or address.get("pedestrian")
        or address.get("footway")
        or address.get("neighbourhood")
        or address.get("suburb")
        or address.get("hamlet")
        or address.get("village")
        or address.get("town")
        or address.get("city")
        or data.get("display_name", "Unknown location").split(",")[0].strip()
    )

    return {
        "name": name,
        "display_name": data.get("display_name", "Unknown location"),
        "approximation": approx,
        "category": data.get("category", ""),
        "type": data.get("type", ""),
        "address": address,
        "namedetails": namedetails,
        "extratags": data.get("extratags") or {},
    }


# ---------------------------------------------------------------------------
# Noise filter
# ---------------------------------------------------------------------------

def is_listing_noise(name: str) -> bool:
    """Return True if the name looks like a rental listing or advertisement."""
    name_lower = (name or "").lower()
    if any(token in name_lower for token in LISTING_NOISE_TOKENS):
        return True
    if len(name_lower) > 72 and any(sym in name_lower for sym in ["$", "@"]):
        return True
    return False


# ---------------------------------------------------------------------------
# Overpass POI queries
# ---------------------------------------------------------------------------

def get_nearby_interesting_pois(
    lat: float, lon: float, radius_m: int = 50, log_prefix: str = ""
) -> List[Dict[str, Any]]:
    """Return named POIs within *radius_m* metres, filtered for watermark usefulness."""
    query = f"""
[out:json];
(
  node(around:{radius_m},{lat},{lon})["name"];
  way(around:{radius_m},{lat},{lon})["name"];
  relation(around:{radius_m},{lat},{lon})["name"];
);
out center;
"""
    features = extract_features(query_osm(query, log_prefix=log_prefix), lat, lon)

    filtered = []
    for feature in features:
        name = feature.get("name", "")
        ftype = (feature.get("type") or "").lower()
        if feature.get("distance_m", 9999) > radius_m:
            continue
        if not name or is_listing_noise(name):
            continue
        if ftype in LOW_VALUE_TYPES:
            continue
        filtered.append(feature)

    return filtered


def get_natural_context_pois(
    lat: float, lon: float, radius_m: int = 250, log_prefix: str = ""
) -> List[Dict[str, Any]]:
    """Fallback query for natural context when the strict nearby query returns nothing."""
    query = f"""
[out:json];
(
  node(around:{radius_m},{lat},{lon})["natural"]["name"];
  way(around:{radius_m},{lat},{lon})["natural"]["name"];
  relation(around:{radius_m},{lat},{lon})["natural"]["name"];
  node(around:{radius_m},{lat},{lon})["waterway"]["name"];
  way(around:{radius_m},{lat},{lon})["waterway"]["name"];
  relation(around:{radius_m},{lat},{lon})["waterway"]["name"];
  way(around:{radius_m},{lat},{lon})["leisure"="park"]["name"];
  relation(around:{radius_m},{lat},{lon})["leisure"="park"]["name"];
  way(around:{radius_m},{lat},{lon})["boundary"="protected_area"]["name"];
  relation(around:{radius_m},{lat},{lon})["boundary"="protected_area"]["name"];
  way(around:{radius_m},{lat},{lon})["highway"~"path|footway"]["name"];
);
out center;
"""
    features = extract_features(query_osm(query, log_prefix=log_prefix), lat, lon)

    filtered = []
    seen_names: set = set()
    for feature in features:
        name = feature.get("name", "")
        ftype = (feature.get("type") or "").lower()
        dist = float(feature.get("distance_m") or 9999)
        if not name or name in seen_names or is_listing_noise(name):
            continue
        if ftype in LOW_VALUE_TYPES:
            continue
        if dist > MAX_NATURAL_CONTEXT_DISTANCE_M:
            continue
        # Natural/area features often have centres outside the strict radius.
        if ftype not in {"water", "bay", "beach", "park", "protected_area", "path", "footway"}:
            if dist > radius_m:
                continue
        seen_names.add(name)
        filtered.append(feature)

    return filtered


def _merge_poi_lists(
    primary: List[Dict[str, Any]], fallback: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge two POI lists, deduplicating by (name, type)."""
    merged: List[Dict[str, Any]] = []
    seen: set = set()
    for poi in primary + fallback:
        key = (
            (poi.get("name") or "").strip().lower(),
            (poi.get("type") or "").strip().lower(),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        merged.append(poi)
    return merged
