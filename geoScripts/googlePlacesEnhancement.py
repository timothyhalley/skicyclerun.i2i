#!/usr/bin/env python3
"""Assemble Google Places landmarks for each geocode cache entry.

This proof-of-concept reuses the CLI of ``wikiLocationEnhancement.py`` but sources
context from Google Maps Platform. It queries the Places Nearby Search v1 API to
capture high-signal landmarks, summarises the area, and stores the outcome under
``google_places_context`` for each record.

Set ``GOOGLE_MAPS_API_KEY`` in your environment before running the helper. In
``--debug`` mode network calls are skipped and request payloads are logged
instead.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

PLACES_API_KEY_ENV: str = "GOOGLE_MAPS_API_KEY"
PLACES_SEARCH_URL: str = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_FIELD_MASK: str = (
    "places.displayName,"
    "places.primaryType,"
    "places.types,"
    "places.shortFormattedAddress,"
    "places.formattedAddress,"
    "places.editorialSummary,"
    "places.rating,"
    "places.userRatingCount,"
    "places.location"
)
PLACES_REQUEST_INTERVAL_SEC: float = 0.35
PLACES_DEFAULT_RADIUS_METERS: int = 320
PLACES_MAX_RESULTS: int = 12

ENV_FILE_CANDIDATES: Tuple[Path, ...] = (
    Path(__file__).resolve().parents[1] / ".env",
    Path.cwd() / ".env",
)

INCLUDED_TYPES: Sequence[str] = (
    "park",
    "tourist_attraction",
    "university",
    "campground",
    "museum",
    "bar",
    "movie_theater",
    "tourist_attraction",
    "subway_station",
    "stadium",
    "art_gallery",
    "airport",
    "restaurant",
)

TYPE_WEIGHTS: Dict[str, float] = {
    "state_park": 9.0,
    "national_park": 9.0,
    "park": 8.0,
    "tourist_attraction": 7.0,
    "natural_feature": 7.0,
    "river": 7.0,
    "waterfall": 7.0,
    "lake": 6.0,
    "university": 8.0,
    "college": 7.0,
    "campus": 6.0,
    "school": 5.0,
    "museum": 7.0,
    "art_gallery": 6.0,
    "memorial": 6.0,
    "historic_site": 6.0,
    "place_of_worship": 5.0,
    "library": 6.0,
    "stadium": 5.0,
    "point_of_interest": 3.5,
    "neighborhood": 3.0,
    "establishment": 2.0,
}

_places_session = requests.Session()
_last_places_request_ts: float = 0.0


def _load_env_files() -> None:
    for path in ENV_FILE_CANDIDATES:
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    if "=" not in stripped:
                        continue
                    key, value = stripped.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
                        logging.debug("🔑 Loaded %s from %s", key, path)
        except OSError as exc:
            logging.debug("⚠️ Skipping env file %s: %s", path, exc)


def _get_places_api_key() -> str:
    api_key = os.getenv(PLACES_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            f"Environment variable {PLACES_API_KEY_ENV} must be set for Google Places access"
        )
    return api_key


def _rate_limited_places_post(
    payload: Dict[str, Any],
    api_key: str,
    *,
    timeout: float = 15.0,
) -> requests.Response:
    global _last_places_request_ts

    now = time.monotonic()
    elapsed = now - _last_places_request_ts
    if elapsed < PLACES_REQUEST_INTERVAL_SEC:
        time.sleep(PLACES_REQUEST_INTERVAL_SEC - elapsed)

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
    }
    response = _places_session.post(
        PLACES_SEARCH_URL,
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    _last_places_request_ts = time.monotonic()
    return response


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a_value = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
        delta_lambda / 2
    ) ** 2
    c_value = 2 * math.atan2(math.sqrt(a_value), math.sqrt(1 - a_value))
    return radius * c_value


def _score_types(types: Iterable[str]) -> float:
    score = 0.0
    for value in types:
        score += TYPE_WEIGHTS.get(value, 0.0)
    return score


def _score_place(place: Dict[str, Any], *, origin: Tuple[float, float], radius: int) -> float:
    types = place.get("types", [])
    score = _score_types(types)
    rating = place.get("rating")
    if rating:
        score += float(rating)
    rating_count = place.get("userRatingCount")
    if rating_count:
        score += min(float(rating_count) / 400.0, 4.5)
    location = place.get("location", {})
    lat = location.get("latitude")
    lon = location.get("longitude")
    if lat is not None and lon is not None:
        distance = _haversine_m(origin[0], origin[1], float(lat), float(lon))
        proximity_bonus = max(radius - distance, 0.0) / max(radius, 1) * 4.0
        score += proximity_bonus
    name = place.get("displayName", {}).get("text") or ""
    lowered = name.lower()
    if "university" in lowered or "college" in lowered:
        score += 3.0
    if "park" in lowered or "river" in lowered or "state park" in lowered:
        score += 3.0
    return score


def _format_highlights(place: Dict[str, Any], *, distance_m: Optional[float]) -> List[str]:
    highlights: List[str] = []
    if distance_m is not None:
        highlights.append(f"{distance_m:.0f} m away")
    primary_type = place.get("primaryType")
    display = place.get("displayName", {}).get("text")
    if primary_type:
        highlights.append(primary_type.replace("_", " "))
    short_address = place.get("shortFormattedAddress") or place.get("formattedAddress")
    if short_address:
        highlights.append(short_address)
    editorial = place.get("editorialSummary", {}).get("overview")
    if editorial:
        highlights.append(editorial)
    if display and primary_type and primary_type not in str(place.get("types", [])):
        highlights.append(primary_type)
    return highlights


def _synthesise_synopsis(landmarks: Sequence[Dict[str, Any]]) -> str:
    if not landmarks:
        return "No high-confidence Google Places landmarks were detected nearby."
    primary_names = [entry["name"] for entry in landmarks[:3]]
    joined = ", ".join(primary_names)
    if len(primary_names) == 1:
        return f"Nearest landmark: {joined}."
    return f"Nearby landmarks include {joined}."


def get_nearby_places(
    lat: Any,
    lon: Any,
    radius: int = PLACES_DEFAULT_RADIUS_METERS,
    *,
    dry_run: bool = False,
    max_results: int = PLACES_MAX_RESULTS,
) -> List[Dict[str, Any]]:
    if lat is None or lon is None:
        return []
    try:
        lat_float = float(lat)
        lon_float = float(lon)
    except (TypeError, ValueError):
        logging.warning("⚠️ Invalid coordinates for Places lookup: lat=%s lon=%s", lat, lon)
        return []

    payload = {
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat_float, "longitude": lon_float},
                "radius": radius,
            }
        },
        "includedTypes": list(INCLUDED_TYPES),
        "maxResultCount": max_results,
        "languageCode": "en",
    }

    if dry_run:
        logging.debug("🌐 Places search payload:%s", "\n" + json.dumps(payload, indent=2))
        return []

    api_key = _get_places_api_key()
    logging.debug(
        "📡 Places search | lat=%.6f lon=%.6f radius=%dm max=%d",
        lat_float,
        lon_float,
        radius,
        max_results,
    )
    start = time.perf_counter()
    response = _rate_limited_places_post(payload, api_key)
    duration = time.perf_counter() - start

    if response.status_code != 200:
        logging.warning(
            "⚠️ Places API request returned %s in %.2fs | body=%s",
            response.status_code,
            duration,
            response.text[:200],
        )
        return []

    data = response.json()
    places = data.get("places", [])
    logging.info("🗺️ Places API returned %d candidates in %.2fs", len(places), duration)
    return places


def build_landmark_package(
    places: Sequence[Dict[str, Any]],
    *,
    origin: Tuple[float, float],
    radius: int,
    limit: int = 6,
) -> Tuple[List[Dict[str, Any]], str]:
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for place in places:
        score = _score_place(place, origin=origin, radius=radius)
        scored.append((score, place))
    scored.sort(key=lambda item: item[0], reverse=True)

    selected: List[Dict[str, Any]] = []
    for score, place in scored[:limit]:
        name = place.get("displayName", {}).get("text")
        if not name:
            continue
        location = place.get("location", {})
        lat = location.get("latitude")
        lon = location.get("longitude")
        distance_m = None
        if lat is not None and lon is not None:
            distance_m = _haversine_m(origin[0], origin[1], float(lat), float(lon))
        highlights = _format_highlights(place, distance_m=distance_m)
        selected.append(
            {
                "id": place.get("name"),
                "name": name,
                "primary_type": place.get("primaryType"),
                "types": place.get("types", []),
                "distance_m": distance_m,
                "highlights": highlights,
                "score": score,
            }
        )

    synopsis = _synthesise_synopsis(selected)
    return selected, synopsis


def _landmark_summary_line(position: int, landmark: Dict[str, Any]) -> str:
    name = landmark.get("name") or "(unnamed)"
    details: List[str] = []

    distance_m = landmark.get("distance_m")
    if isinstance(distance_m, (int, float)):
        details.append(f"{distance_m:.0f} m away")

    primary_type = landmark.get("primary_type")
    if primary_type:
        readable = primary_type.replace("_", " ")
        if readable not in details:
            details.append(readable)

    for item in landmark.get("highlights", []) or []:
        normalized = item.strip()
        lower = normalized.lower()
        if lower.startswith("rating ") or " reviews" in lower:
            continue
        if normalized and normalized not in details:
            details.append(normalized)

    if not details:
        types = landmark.get("types", [])
        if types:
            details.append(types[0].replace("_", " "))

    suffix = f" — {'; '.join(details)}" if details else ""
    return f"  {position}) {name}{suffix}"


def _write_updates(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def _iso_utc_now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attach Google Places landmarks to location metadata",
    )
    parser.add_argument(
        "--master-store",
        required=True,
        help="Path to JSON input file to augment",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Log request payloads without performing HTTP calls",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=PLACES_DEFAULT_RADIUS_METERS,
        help="Search radius in meters for Places API lookups",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if (args.verbose or args.debug) else logging.INFO,
        format="%(message)s",
    )

    _load_env_files()

    logging.info("📥 Loading metadata from %s", args.master_store)
    try:
        with open(args.master_store, "r", encoding="utf-8") as handle:
            data: Dict[str, Any] = json.load(handle)
    except FileNotFoundError:
        logging.error("❌ Input file not found: %s", args.master_store)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        logging.error("❌ Invalid JSON in %s: %s", args.master_store, exc)
        sys.exit(1)

    updates = 0
    for index, (coord_key, entry) in enumerate(data.items(), start=1):
        logging.info("")
        logging.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logging.info(
            "📍 #%d %s | %s",
            index,
            coord_key,
            entry.get("display_name") or "(no display name)",
        )

        lat = entry.get("lat")
        lon = entry.get("lon")
        if lat is None or lon is None:
            logging.warning("⚠️ Missing coordinates; skipping Places lookup")
            continue

        if args.debug:
            get_nearby_places(lat, lon, args.radius, dry_run=True)
            context = entry.get("google_places_context") or {}
            landmarks = context.get("landmarks", [])
            synopsis = context.get("synopsis")

            if synopsis:
                logging.info("🧭 Cached landmarks synopsis: %s", synopsis)
            elif landmarks:
                logging.info("🧭 Cached landmarks synopsis unavailable; listing landmarks")
            else:
                logging.info("ℹ️ No cached Google Places context available for debug view")

            for pos, landmark in enumerate(landmarks, start=1):
                logging.info(_landmark_summary_line(pos, landmark))
            logging.debug("🛑 Debug mode enabled; skipping live Places lookup")
            continue

        try:
            places = get_nearby_places(lat, lon, args.radius, dry_run=False)
        except RuntimeError as exc:
            logging.error("❌ %s", exc)
            sys.exit(1)

        if not places:
            logging.warning("⚠️ No Google Places candidates discovered")
            entry["google_places_context"] = {
                "retrieved_at": _iso_utc_now(),
                "radius_m": args.radius,
                "landmarks": [],
                "synopsis": "",
            }
            updates += 1
            continue

        origin = (float(lat), float(lon))
        landmarks, synopsis = build_landmark_package(places, origin=origin, radius=args.radius)

        if not landmarks:
            logging.warning("⚠️ Places API results lacked usable display names")
            entry["google_places_context"] = {
                "retrieved_at": _iso_utc_now(),
                "radius_m": args.radius,
                "landmarks": [],
                "synopsis": synopsis,
            }
            updates += 1
            continue

        logging.info("🧭 Landmarks synopsis: %s", synopsis)
        for pos, landmark in enumerate(landmarks, start=1):
            logging.info(_landmark_summary_line(pos, landmark))

        entry["google_places_context"] = {
            "retrieved_at": _iso_utc_now(),
            "radius_m": args.radius,
            "landmarks": landmarks,
            "synopsis": synopsis,
        }
        updates += 1

    if updates and not args.debug:
        logging.info("💾 Writing updated metadata with %d Google Places contexts", updates)
        _write_updates(args.master_store, data)
    else:
        logging.info("🟰 No updates written; existing file unchanged")


if __name__ == "__main__":
    main()
