"""Known location hints — load from config and match against GPS + reverse-geocode."""
from pathlib import Path
from typing import Any, Dict, List, Optional

from .poi_constants import LOW_VALUE_HERE_TYPES, NATURAL_NAME_HINTS
from .poi_geo_utils import haversine

KNOWN_LOCATION_HINTS_PATH = Path(__file__).parent.parent / "config" / "known_location_hints.json"


def load_known_location_hints() -> List[Dict[str, Any]]:
    """Return the hints list from ``config/known_location_hints.json``."""
    if not KNOWN_LOCATION_HINTS_PATH.exists():
        return []

    try:
        import json
        with open(KNOWN_LOCATION_HINTS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"[Hints] Failed to load {KNOWN_LOCATION_HINTS_PATH.name}: {exc}")
        return []

    hints = payload.get("hints", []) if isinstance(payload, dict) else []
    normalized: List[Dict[str, Any]] = []
    for hint in hints:
        if not isinstance(hint, dict):
            continue
        try:
            normalized.append(
                {
                    "id": str(hint.get("id") or hint.get("name") or "").strip(),
                    "name": str(hint.get("name") or "").strip(),
                    "lat": float(hint.get("lat")),
                    "lon": float(hint.get("lon")),
                    "radius_m": float(hint.get("radius_m", 100)),
                    "line1": str(hint.get("line1") or hint.get("name") or "").strip(),
                    "line1_en": str(hint.get("line1_en") or "").strip(),
                    "line2": str(hint.get("line2") or "").strip(),
                    "line2_en": str(hint.get("line2_en") or "").strip(),
                    "when_here_types": [
                        str(v).strip().lower()
                        for v in hint.get("when_here_types", [])
                        if v
                    ],
                    "enabled": bool(hint.get("enabled", True)),
                }
            )
        except Exception:
            continue
    return normalized


def match_known_location_hint(
    lat: float, lon: float, reverse_info: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Return the nearest enabled hint within its radius, or ``None``."""
    hints = load_known_location_hints()
    if not hints:
        return None

    here_type = (
        (reverse_info.get("type") or reverse_info.get("category") or "").strip().lower()
    )
    approx = (reverse_info.get("approximation") or "").strip().lower()
    address = reverse_info.get("address") or {}
    road = (address.get("road") or "").strip().lower()
    house_number = (address.get("house_number") or "").strip().lower()

    reverse_is_low_value_or_unresolved = (
        not here_type
        or here_type in LOW_VALUE_HERE_TYPES
        or bool(road)
        or bool(house_number)
    )

    best_match: Optional[Dict[str, Any]] = None
    best_distance: Optional[float] = None

    for hint in hints:
        if not hint.get("enabled"):
            continue

        when_here_types = hint.get("when_here_types") or []
        if when_here_types:
            candidate_values = {v for v in [here_type, approx, road] if v}
            configured_low_value = any(v in LOW_VALUE_HERE_TYPES for v in when_here_types)
            if not any(v in when_here_types for v in candidate_values):
                if not (configured_low_value and reverse_is_low_value_or_unresolved):
                    continue

        distance_m = haversine(lat, lon, hint["lat"], hint["lon"])
        if distance_m > hint["radius_m"]:
            continue

        if best_distance is None or distance_m < best_distance:
            best_distance = distance_m
            best_match = {**hint, "distance_m": distance_m}

    return best_match
