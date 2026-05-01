"""Overpass API client — rate limiter, query executor, feature extractor."""
import random
import time
from typing import Any, Dict, List

import requests

from .poi_geo_utils import bearing_to_cardinal, haversine, initial_bearing

OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


class OverpassRateLimiter:
    """Enforce minimum delay between Overpass API requests to avoid 429s.

    Strategy:
    - 1.0 s minimum gap between individual queries within a photo.
    - ``reset_for_new_photo()`` backdates ``last_request_time`` so the *first*
      query of each new photo naturally waits ~INTER_PHOTO_PAUSE seconds,
      giving the server breathing space without piling up delays per query.
    - Backoff on HTTP errors is capped so a run of transient failures does not
      snowball into multi-second pauses on every query.
    """

    MIN_DELAY_SECONDS = 1.0
    INTER_PHOTO_PAUSE = 2.0

    def __init__(self) -> None:
        self.last_request_time: float | None = None
        self.consecutive_failures: int = 0

    def reset_for_new_photo(self) -> None:
        """Call between photos to ensure a clean ~2 s gap before the next batch."""
        self.consecutive_failures = 0
        self.last_request_time = time.time() - (self.INTER_PHOTO_PAUSE - self.MIN_DELAY_SECONDS)

    def wait_if_needed(self) -> None:
        if self.last_request_time is None:
            return
        elapsed = time.time() - self.last_request_time
        if elapsed < self.MIN_DELAY_SECONDS:
            time.sleep(self.MIN_DELAY_SECONDS - elapsed)

    def record_success(self) -> None:
        self.last_request_time = time.time()
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_request_time = time.time()

    def get_backoff_wait(self, attempt: int) -> float:
        base = min(2 ** attempt * 1.5 + random.uniform(0, 1), 30)
        if self.consecutive_failures > 4:
            base = min(base * 1.5, 30)
        return base


# Module-level singleton shared across all callers in a process.
_limiter = OverpassRateLimiter()

_stats: Dict[str, int] = {
    "requests_attempted": 0,
    "requests_succeeded": 0,
    "http_errors": 0,
    "timeouts": 0,
    "request_exceptions": 0,
    "retry_waits": 0,
    "queries_failed": 0,
}


def reset_overpass_stats() -> None:
    """Reset module-level Overpass request counters."""
    for key in list(_stats.keys()):
        _stats[key] = 0


def get_overpass_stats() -> Dict[str, int]:
    """Return a copy of current Overpass request counters."""
    return dict(_stats)


def query_osm(
    query: str, max_retries: int = 6, log_prefix: str = ""
) -> List[Dict[str, Any]]:
    """Execute an Overpass QL query and return the ``elements`` list."""
    headers = {
        "User-Agent": "SkiCycleRun-POI-Watermark/1.0",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    for attempt in range(max_retries):
        _limiter.wait_if_needed()
        server = random.choice(OVERPASS_SERVERS)
        _stats["requests_attempted"] += 1
        try:
            response = requests.post(server, data={"data": query}, headers=headers, timeout=60)
            if response.status_code in (429, 502, 503, 504):
                wait = _limiter.get_backoff_wait(attempt)
                _limiter.record_failure()
                _stats["http_errors"] += 1
                _stats["retry_waits"] += 1
                print(
                    f"{log_prefix}[Overpass] HTTP {response.status_code} from {server} "
                    f"(attempt {attempt + 1}/{max_retries}). Back off {wait:.1f}s…"
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            _limiter.record_success()
            _stats["requests_succeeded"] += 1
            return response.json().get("elements", [])
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            _limiter.record_failure()
            _stats["http_errors"] += 1

            # 4xx errors (except 429) are typically query/payload compatibility issues.
            # Retrying with backoff only burns time and repeats noisy logs.
            if status_code is not None and 400 <= status_code < 500 and status_code != 429:
                body_preview = ""
                if exc.response is not None and exc.response.text:
                    body_preview = exc.response.text.strip().replace("\n", " ")[:180]
                detail = f" | response: {body_preview}" if body_preview else ""
                print(
                    f"{log_prefix}[Overpass] NON-RETRYABLE HTTP {status_code} from {server} "
                    f"(attempt {attempt + 1}/{max_retries}). Aborting retries.{detail}"
                )
                _stats["queries_failed"] += 1
                return []

            wait = _limiter.get_backoff_wait(attempt)
            _stats["retry_waits"] += 1
            print(
                f"{log_prefix}[Overpass] HTTP error on {server} "
                f"(attempt {attempt + 1}/{max_retries}): {exc}. Back off {wait:.1f}s…"
            )
            time.sleep(wait)
        except requests.exceptions.Timeout:
            wait = _limiter.get_backoff_wait(attempt)
            _limiter.record_failure()
            _stats["timeouts"] += 1
            _stats["retry_waits"] += 1
            print(
                f"{log_prefix}[Overpass] Timeout on {server} "
                f"(attempt {attempt + 1}/{max_retries}). Back off {wait:.1f}s…"
            )
            time.sleep(wait)
        except requests.exceptions.RequestException as exc:
            wait = _limiter.get_backoff_wait(attempt)
            _limiter.record_failure()
            _stats["request_exceptions"] += 1
            _stats["retry_waits"] += 1
            print(
                f"{log_prefix}[Overpass] Error on {server} "
                f"(attempt {attempt + 1}/{max_retries}): {exc}. Back off {wait:.1f}s…"
            )
            time.sleep(wait)

    print(f"{log_prefix}[Overpass] FAILED after all retries.")
    _stats["queries_failed"] += 1
    return []


def extract_features(
    elements: List[Dict[str, Any]], lat: float, lon: float
) -> List[Dict[str, Any]]:
    """Parse raw Overpass elements into typed feature dicts sorted by distance."""
    features = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        if "lat" in el and "lon" in el:
            lat2, lon2 = el["lat"], el["lon"]
        else:
            center = el.get("center")
            if not center:
                continue
            lat2, lon2 = center["lat"], center["lon"]

        dist = haversine(lat, lon, lat2, lon2)
        bearing = initial_bearing(lat, lon, lat2, lon2)

        ftype = (
            tags.get("amenity")
            or tags.get("shop")
            or tags.get("tourism")
            or tags.get("leisure")
            or tags.get("natural")
            or tags.get("boundary")
            or tags.get("place")
            or tags.get("highway")
        )

        features.append(
            {
                "name": name,
                "type": ftype,
                "distance_m": dist,
                "bearing_deg": bearing,
                "bearing_cardinal": bearing_to_cardinal(bearing),
                "lat": lat2,
                "lon": lon2,
                "tags": tags,
            }
        )

    return sorted(features, key=lambda x: x["distance_m"])
