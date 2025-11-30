#!/usr/bin/env python3
"""Append Wikipedia context to geocode cache entries.

This helper reads the master/geocode JSON produced by the pipeline and, for
each entry that exposes an ``extratags.wikipedia`` value, fetches a short
summary from the public Wikipedia REST API. Retrieved context is stored under
``wiki_summary`` alongside the existing record without mutating other fields.

To enrich candidate selection, the helper also queries the Overpass API for
notable nearby OpenStreetMap features, weaving historic or touristic context
into the synopsis we build before contacting Wikipedia.

Rate limiting defaults to one request per second via
``WIKI_REQUEST_INTERVAL_SEC`` so we stay polite with the upstream API. Adjust
only if you have explicit approval to increase throughput.

CLI usage::

    python3 wikiLocationEnhancement.py --master-store metadata/geocode_cache.json

Add ``--verbose`` for debug output covering skips and cache hits.
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, Iterable, List, Optional

import requests

WIKI_REQUEST_INTERVAL_SEC: float = 1.0
"""Minimum delay (seconds) between Wikipedia API calls."""

WIKI_SUMMARY_ENDPOINT: str = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
"""Wikipedia REST endpoint template for summary lookups."""

WIKI_USER_AGENT_ENV: str = "WIKI_USER_AGENT"
"""Environment variable controlling the User-Agent header for Wikipedia."""

DEFAULT_WIKI_USER_AGENT: str = "SkiCycleRun/V04.015 (https://skicyclerun.com/about)"
"""Fallback User-Agent if none supplied via environment."""

OVERPASS_URL: str = "https://overpass-api.de/api/interpreter"
"""Overpass API endpoint for OSM queries."""

OVERPASS_REQUEST_INTERVAL_SEC: float = 2.0
"""Minimum delay (seconds) between Overpass API calls."""

OVERPASS_DEFAULT_RADIUS_METERS: int = 250
"""Default search radius (meters) for nearby feature lookups."""

_last_request_ts: float = 0.0
_overpass_last_request_ts: float = 0.0


def _wiki_headers() -> Dict[str, str]:
    """Build headers for Wikipedia requests, honoring override env vars."""

    user_agent = os.getenv(WIKI_USER_AGENT_ENV, DEFAULT_WIKI_USER_AGENT)
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
    }

def _rate_limited_get(url: str, *, timeout: float = 10.0) -> requests.Response:
    """Perform a GET request while enforcing the global rate limit."""
    global _last_request_ts
    now = time.monotonic()
    elapsed = now - _last_request_ts
    if elapsed < WIKI_REQUEST_INTERVAL_SEC:
        time.sleep(WIKI_REQUEST_INTERVAL_SEC - elapsed)
    resp = requests.get(url, headers=_wiki_headers(), timeout=timeout)
    _last_request_ts = time.monotonic()
    return resp


def _rate_limited_overpass_post(query: str, *, timeout: float = 30.0) -> requests.Response:
    """Submit an Overpass query while enforcing a polite rate limit."""

    global _overpass_last_request_ts
    now = time.monotonic()
    elapsed = now - _overpass_last_request_ts
    if elapsed < OVERPASS_REQUEST_INTERVAL_SEC:
        time.sleep(OVERPASS_REQUEST_INTERVAL_SEC - elapsed)
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=timeout)
    _overpass_last_request_ts = time.monotonic()
    return resp


def get_nearby_features(
    lat: Any,
    lon: Any,
    radius: int = OVERPASS_DEFAULT_RADIUS_METERS,
    *,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Query Overpass API for notable features around the provided coordinate."""

    if lat is None or lon is None:
        return []

    try:
        lat_float = float(lat)
        lon_float = float(lon)
    except (TypeError, ValueError):
        logging.warning("⚠️ Invalid coordinates for Overpass lookup: lat=%s lon=%s", lat, lon)
        return []

    query = f"""
    [out:json][timeout:25];
    (
        node(around:{radius},{lat_float},{lon_float})[\"amenity\"];
        way(around:{radius},{lat_float},{lon_float})[\"building\"];
        node(around:{radius},{lat_float},{lon_float})[\"tourism\"];
        way(around:{radius},{lat_float},{lon_float})[\"leisure\"];
        way(around:{radius},{lat_float},{lon_float})[\"historic\"];
        node(around:{radius},{lat_float},{lon_float})[\"historic\"];
    );
    out tags center;
    """

    logging.debug(
        "🛰️ Querying Overpass around (%.6f, %.6f) radius=%dm",
        lat_float,
        lon_float,
        radius,
    )
    logging.debug("🧾 Overpass QL:%s%s", "\n", query.strip())

    if dry_run:
        logging.debug("🛑 Debug mode enabled; skipping Overpass network request")
        return []

    start = time.perf_counter()
    try:
        resp = _rate_limited_overpass_post(query)
        duration = time.perf_counter() - start
    except requests.RequestException as exc:
        duration = time.perf_counter() - start
        logging.warning(
            "⚠️ Overpass request failed after %.2fs: %s",
            duration,
            exc,
        )
        return []

    if resp.status_code != 200:
        logging.warning(
            "⚠️ Overpass request returned status %s in %.2fs",
            resp.status_code,
            duration,
        )
        return []

    payload = resp.json()
    elements = payload.get("elements", [])
    logging.info("📡 Overpass returned %d features in %.2fs", len(elements), duration)

    lines: List[str] = []
    for idx, element in enumerate(elements, start=1):
        tags = element.get("tags", {}) or {}
        name = tags.get("name") or "(unnamed)"
        feature_kind = (
            tags.get("amenity")
            or tags.get("building")
            or tags.get("tourism")
            or tags.get("leisure")
            or tags.get("historic")
            or element.get("type")
        )
        notable = []
        for key in ("historic", "tourism", "amenity", "wikidata", "wikipedia"):
            value = tags.get(key)
            if value:
                notable.append(f"{key}={value}")
        detail = ", ".join(notable)
        lines.append(f"\n  • #{idx} {feature_kind or 'feature'}: {name}{(' | ' + detail) if detail else ''}")

    if lines:
        logging.debug("🧭 Nearby feature snapshot:%s", "".join(lines))

    return elements
def fetch_wikipedia_summary(page_title: str) -> Optional[Dict[str, Any]]:
    """Fetch structured summary data for the given Wikipedia page title."""
    safe_title = requests.utils.quote(page_title)
    url = WIKI_SUMMARY_ENDPOINT.format(title=safe_title)
    logging.debug("🧭 Fetching summary | page='%s' | url=%s", page_title, url)
    start = time.perf_counter()
    try:
        resp = _rate_limited_get(url)
        duration = time.perf_counter() - start
    except requests.RequestException as exc:
        duration = time.perf_counter() - start
        logging.warning(
            "⚠️ Wikipedia request failed for '%s' after %.2fs: %s",
            page_title,
            duration,
            exc,
        )
        return None

    if resp.status_code != 200:
        logging.warning(
            "⚠️ Wikipedia request for '%s' returned status %s in %.2fs",
            page_title,
            resp.status_code,
            duration,
        )
        return None

    data = resp.json()
    summary = {
        "title": data.get("title"),
        "description": data.get("description"),
        "extract": data.get("extract"),
        "url": data.get("content_urls", {}).get("desktop", {}).get("page")
                or data.get("content_urls", {}).get("mobile", {}).get("page"),
        "source": url,
        "timestamp": data.get("timestamp"),
    }
    logging.info(
        "✅ Retrieved summary for '%s' in %.2fs",
        summary.get("title") or page_title,
        duration,
    )
    return summary


def _candidate_titles(
    entry: Dict[str, Any],
    nearby_features: Iterable[Dict[str, Any]] = (),
) -> List[str]:
    """Build ordered, de-duplicated candidate page titles for a location entry."""

    seen: Dict[str, None] = {}
    extratags = entry.get("extratags", {}) or {}
    namedetails = entry.get("namedetails", {}) or {}

    category = (entry.get("category") or "").replace("_", " ").strip()
    entry_type = (entry.get("type") or "").replace("_", " ").strip()
    display_name = (entry.get("display_name") or "").strip()
    location_bits = [entry.get("city"), entry.get("state"), entry.get("country")]
    location_context = ", ".join(bit for bit in location_bits if bit)

    def _add(values: Iterable[Optional[str]]) -> None:
        for value in values:
            if not value:
                continue
            candidate = " ".join(str(value).split())
            if not candidate:
                continue
            if candidate not in seen:
                seen[candidate] = None

    # 1. Explicit Wikipedia short title (language prefix stripped).
    wiki_tag = extratags.get("wikipedia")
    if wiki_tag:
        _add([wiki_tag.split(":", 1)[-1] if ":" in wiki_tag else wiki_tag])

    # 2. Core name from namedetails (preferred) or extratags.
    name_keys = ("name", "official_name", "short_name", "alt_name", "name:en")
    core_name = next((namedetails.get(key) for key in name_keys if namedetails.get(key)), None)
    if not core_name:
        core_name = next((extratags.get(key) for key in name_keys if extratags.get(key)), None)

    _add([core_name])

    # Include alternates for traceability.
    _add(namedetails.get(key) for key in name_keys)
    _add(extratags.get(key) for key in name_keys)

    # 3. Display name variations.
    if display_name:
        primary = display_name.split(",", 1)[0].strip()
        _add([primary])
        _add([display_name])

    # 4. Context-enriched combinations.
    if core_name:
        context_parts = [core_name]
        if entry_type:
            context_parts.append(entry_type)
        if category and category != entry_type:
            context_parts.append(category)
        if location_context:
            context_parts.append(location_context)
        _add([" - ".join(context_parts)])

    if display_name and (entry_type or category):
        context = " ".join(part for part in (entry_type, category) if part)
        _add([f"{display_name} ({context})"])

    if display_name and location_context:
        _add([f"{display_name} - {location_context}"])

    for feature in nearby_features:
        tags = feature.get("tags", {}) or {}
        feature_names = [
            tags.get("name"),
            tags.get("official_name"),
            tags.get("alt_name"),
            tags.get("name:en"),
        ]
        _add(feature_names)

        feature_wiki = tags.get("wikipedia")
        if feature_wiki:
            _add([feature_wiki.split(":", 1)[-1]])

        historic = tags.get("historic")
        tourism = tags.get("tourism")
        if feature_names[0] and (historic or tourism):
            context_label = historic or tourism
            _add([f"{feature_names[0]} {context_label}"])

    return list(seen.keys())[:8]

def main() -> None:
    parser = argparse.ArgumentParser(description="Attach Wikipedia summaries to location metadata")
    parser.add_argument("--master-store", required=True, help="Path to JSON input file to augment")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print candidate generation details without performing HTTP requests",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if (args.verbose or args.debug) else logging.INFO,
        format="%(message)s",
    )

    logging.info("📥 Loading metadata from %s", args.master_store)
    try:
        with open(args.master_store, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
    except FileNotFoundError:
        logging.error("❌ Input file not found: %s", args.master_store)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        logging.error("❌ Invalid JSON in %s: %s", args.master_store, exc)
        sys.exit(1)

    updates = 0
    for coord_key, entry in data.items():
        if entry.get("wiki_summary"):
            logging.debug("ℹ️ Wiki summary already present for %s; skipping", coord_key)
            continue

        logging.debug(
            "🔍 Context | coord=%s | display='%s' | namedetails=%s | extratags=%s",
            coord_key,
            entry.get("display_name"),
            entry.get("namedetails"),
            entry.get("extratags"),
        )
        nearby_features: List[Dict[str, Any]] = []
        if entry.get("lat") is not None and entry.get("lon") is not None:
            nearby_features = get_nearby_features(
                entry.get("lat"),
                entry.get("lon"),
                dry_run=args.debug,
            )
        else:
            logging.debug(
                "🚫 Missing coordinates for %s; skipping Overpass lookup",
                coord_key,
            )

        historic_notes: List[str] = []
        for feature in nearby_features:
            tags = feature.get("tags", {}) or {}
            name = tags.get("name") or "(unnamed)"
            if tags.get("historic"):
                note_parts = [tags.get("historic")]
                if tags.get("start_date"):
                    note_parts.append(f"est. {tags.get('start_date')}")
                historic_notes.append(f"\n  • {name} — {' | '.join(note_parts)}")

        if historic_notes:
            logging.info("🏛️ Historic context detected:%s", "".join(historic_notes))

        candidates = _candidate_titles(entry, nearby_features)
        if not candidates:
            logging.debug("🚫 No candidate titles derived for %s; skipping", coord_key)
            continue

        formatted_candidates = "".join(f"\n  • {candidate}" for candidate in candidates)
        logging.debug(
            "🧠 Candidate titles from metadata + %d nearby features:%s",
            len(nearby_features),
            formatted_candidates,
        )

        if args.debug:
            for candidate in candidates:
                safe = requests.utils.quote(candidate)
                url = WIKI_SUMMARY_ENDPOINT.format(title=safe)
                logging.debug("🌐 Request URL for '%s':\n%s", candidate, url)
            continue

        summary: Optional[Dict[str, Any]] = None
        for candidate in candidates:
            logging.debug("📝 Trying candidate '%s' for %s", candidate, coord_key)
            summary = fetch_wikipedia_summary(candidate)
            if summary:
                summary.setdefault("resolved_title", candidate)
                break

        if summary:
            entry["wiki_summary"] = summary
            updates += 1
        else:
            logging.warning(
                "⚠️ No summary retrieved after %d attempts (%s)",
                len(candidates),
                coord_key,
            )

    if updates:
        logging.info("💾 Writing updated metadata with %d new summaries", updates)
        with open(args.master_store, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    else:
        logging.info("🟰 No updates written; existing file unchanged")

if __name__ == "__main__":
    main()