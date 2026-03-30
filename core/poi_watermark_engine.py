"""POI watermark engine — per-photo and batch pipeline entry points.

This is the public API consumed by both the CLI (geoScripts/poi_Watermark.py) and the
pipeline stage (pipeline.py → run_post_lora_watermarking_stage).

Public functions:
    process_photo(image_path, *, lat, lon, ...) → dict
    process_folder(folder, ...) → list[dict]
"""
import datetime
import glob
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .poi_constants import AREA_CONTEXT_TYPES, DIRECT_POI_LINE1_TYPES, MAX_NATURAL_CONTEXT_DISTANCE_M, TRAIL_TYPES
from .poi_exif import get_exif_gps
from .poi_formatter import (
    build_two_line_watermark,
    format_bilingual,
    format_line2,
    format_poi_inline,
    get_feature_english_name,
)
from .poi_location_hints import match_known_location_hint
from .poi_osm_queries import (
    _merge_poi_lists,
    get_natural_context_pois,
    get_nearby_interesting_pois,
    reverse_lookup_free,
)
from .poi_overpass import _limiter
from .poi_selection import choose_line1_poi, derive_here_place, select_watermark_pois

# ---------------------------------------------------------------------------
# Config loading (pipeline_config.json is one directory above core/)
# ---------------------------------------------------------------------------

_PIPELINE_CONFIG_PATH = Path(__file__).parent.parent / "config" / "pipeline_config.json"


def _load_bilingual_output(default: bool = True) -> bool:
    try:
        with open(_PIPELINE_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        wm_cfg = cfg.get("watermark", {}) if isinstance(cfg, dict) else {}
        return bool(wm_cfg.get("bilingual_output", default))
    except Exception:
        return default


def _load_copyright_string() -> str:
    """Build copyright string from pipeline_config.json watermark settings."""
    try:
        with open(_PIPELINE_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        wm_cfg = cfg.get("watermark", {}) if isinstance(cfg, dict) else {}
        fmt = (wm_cfg.get("copyright_line", {}) or {}).get(
            "format", "SkiCycleRun © {year} {symbol}"
        )
        symbol = (wm_cfg.get("symbol") or "▲").strip()
        year = wm_cfg.get("fixed_year") or datetime.datetime.now().year
        return fmt.format(year=year, symbol=symbol)
    except Exception:
        return ""


def _load_line1_rule_config() -> Dict[str, Any]:
    """Load configurable LINE 1 rule settings from pipeline_config watermark block."""
    defaults: Dict[str, Any] = {
        "separator": " · ",
        "context_types": [
            "street",
            "monument",
            "park",
            "trailhead",
            "beach",
            "peak",
            "waterfall",
            "memorial",
            "attraction",
            "forest",
            "national_park",
        ],
        "experience_types_priority": [
            "restaurant",
            "cafe",
            "hotel",
            "view",
            "monument",
            "memorial",
            "attraction",
        ],
    }
    try:
        with open(_PIPELINE_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        wm_cfg = cfg.get("watermark", {}) if isinstance(cfg, dict) else {}
        line1_cfg = wm_cfg.get("line1_rule", {}) if isinstance(wm_cfg, dict) else {}
        if not isinstance(line1_cfg, dict):
            return defaults
        merged = {**defaults, **line1_cfg}
        return merged
    except Exception:
        return defaults


def _load_poi_filter_config() -> Dict[str, Any]:
    """Load POI filtering knobs for watermark context selection."""
    defaults: Dict[str, Any] = {
        "max_distance_m": 75,
        "limit": 3,
        "allowed_categories": ["restaurant", "cafe", "bar", "hotel", "view", "landmark", "museum", "shop"],
        "category_priority": {
            "restaurant": 0,
            "cafe": 1,
            "bar": 2,
            "hotel": 3,
            "view": 4,
            "landmark": 5,
            "museum": 6,
            "shop": 7,
        },
    }
    try:
        with open(_PIPELINE_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        wm_cfg = cfg.get("watermark", {}) if isinstance(cfg, dict) else {}
        pf_cfg = wm_cfg.get("poi_filter", {}) if isinstance(wm_cfg, dict) else {}
        if not isinstance(pf_cfg, dict):
            return defaults
        merged = {**defaults, **pf_cfg}
        return merged
    except Exception:
        return defaults


# Module-level defaults (loaded once at import time).
BILINGUAL_OUTPUT: bool = _load_bilingual_output(True)
COPYRIGHT_STRING: str = _load_copyright_string()
LINE1_RULE_CONFIG: Dict[str, Any] = _load_line1_rule_config()
POI_FILTER_CONFIG: Dict[str, Any] = _load_poi_filter_config()


# ---------------------------------------------------------------------------
# Per-photo processor
# ---------------------------------------------------------------------------

def process_photo(
    image_path: str,
    style: str = "emoji",
    bilingual_output: bool = BILINGUAL_OUTPUT,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Generate watermark text for a single photo.

    GPS coordinates can be supplied directly via *lat*/*lon* (e.g. from
    pipeline master.json metadata) to skip EXIF reading — useful when the
    image being watermarked is a LoRA-processed copy that lacks EXIF GPS.

    Returns a dict with at least ``line1``, ``line2``, and ``watermark`` keys.
    """
    _limiter.reset_for_new_photo()

    # --- GPS resolution ---
    if lat is None or lon is None:
        gps = get_exif_gps(image_path)
        if not gps:
            return {
                "image": image_path,
                "lat": None,
                "lon": None,
                "no_gps": True,
                "line1": "",
                "line2": COPYRIGHT_STRING,
                "watermark": COPYRIGHT_STRING,
            }
        lat, lon = gps

    # --- Reverse geocode ---
    reverse_info = reverse_lookup_free(lat, lon)
    reverse_info_en: Dict[str, Any] = {}
    if bilingual_output:
        try:
            reverse_info_en = reverse_lookup_free(lat, lon, accept_language="en")
        except Exception:
            reverse_info_en = {}

    # --- Known location hints ---
    known_hint = match_known_location_hint(lat, lon, reverse_info)

    # --- Nearby POI queries (skipped when a hint overrides everything) ---
    nearby_pois: List[Dict[str, Any]] = []
    if not known_hint:
        nearby_pois = get_nearby_interesting_pois(lat, lon, radius_m=50)
        if not nearby_pois:
            nearby_pois = _merge_poi_lists(
                nearby_pois, get_natural_context_pois(lat, lon, radius_m=250)
            )

        # Keep watermark context concise and readable.
        nearby_pois = select_watermark_pois(
            nearby_pois,
            max_distance_m=float(POI_FILTER_CONFIG.get("max_distance_m", 75)),
            limit=int(POI_FILTER_CONFIG.get("limit", 3)),
            allowed_categories=POI_FILTER_CONFIG.get("allowed_categories"),
            category_priority=POI_FILTER_CONFIG.get("category_priority"),
        )

    here_place = derive_here_place(reverse_info, nearby_pois)
    line1, line2 = build_two_line_watermark(
        reverse_info,
        here_place,
        nearby_pois,
        known_hint=known_hint,
        line1_rule_config=LINE1_RULE_CONFIG,
    )

    # --- Bilingual merge ---
    if bilingual_output and reverse_info_en:
        line1_en = ""
        line2_en = ""

        if known_hint:
            line1_en = str(known_hint.get("line1_en") or "").strip()
            line2_en = str(known_hint.get("line2_en") or "").strip()
        else:
            best_line1_poi = choose_line1_poi(here_place, nearby_pois)
            best_type = (best_line1_poi.get("type") or "").lower() if best_line1_poi else ""

            # Trail + area context
            if best_line1_poi and best_type in TRAIL_TYPES:
                trail_en = get_feature_english_name(best_line1_poi)
                trail_name = (best_line1_poi.get("name") or "").strip()
                area_candidates = []
                for candidate in nearby_pois:
                    c_name = (candidate.get("name") or "").strip()
                    c_type = (candidate.get("type") or "").lower()
                    c_dist = float(candidate.get("distance_m") or 9999)
                    if not c_name or c_name == trail_name:
                        continue
                    if c_type in AREA_CONTEXT_TYPES and c_dist <= MAX_NATURAL_CONTEXT_DISTANCE_M:
                        area_candidates.append((c_dist, candidate))
                if trail_en and area_candidates:
                    area_candidates.sort(key=lambda x: x[0])
                    area_en = get_feature_english_name(area_candidates[0][1])
                    if area_en:
                        line1_en = f"{trail_en} on {area_en}"

            # Direct POI with distance
            if not line1_en and best_line1_poi:
                poi_en = get_feature_english_name(best_line1_poi)
                if poi_en:
                    dist = best_line1_poi.get("distance_m")
                    direction = best_line1_poi.get("bearing_cardinal")
                    if best_type in DIRECT_POI_LINE1_TYPES and dist not in (None, 0):
                        line1_en = (
                            f"{poi_en} ({dist:.0f}m {direction})"
                            if direction
                            else f"{poi_en} ({dist:.0f}m)"
                        )
                    else:
                        line1_en = poi_en

            # Approximation fallback
            if not line1_en:
                approx_native = (reverse_info.get("approximation") or "").strip()
                approx_en = (reverse_info_en.get("approximation") or "").strip()
                if line1 == approx_native and approx_en:
                    line1_en = approx_en

        if not line2_en:
            line2_en = format_line2(reverse_info_en)

        line1 = format_bilingual(line1, line1_en)
        line2 = format_bilingual(line2, line2_en)

    # --- Copyright brand ---
    if COPYRIGHT_STRING:
        line2 = f"{line2}  {COPYRIGHT_STRING}"

    # --- Terminal output ---
    here_summary_parts = []
    if here_place:
        here_summary_parts.append(format_poi_inline(here_place))
    else:
        here_summary_parts.append(
            f"{reverse_info.get('approximation', 'Unknown location')} [approximation]"
        )
    for poi in nearby_pois[:3]:
        if not here_place or poi.get("name") != here_place.get("name"):
            here_summary_parts.append(format_poi_inline(poi))

    print(f"    🌎 {lat:.6f}, {lon:.6f} --> {reverse_info['display_name']}")
    if known_hint:
        print(f"    🧭 HINT --> {known_hint['line1']} ({known_hint['distance_m']:.0f}m)")
    print(f"    📍 HERE --> {', '.join(here_summary_parts)}")
    print("    ✨ NEARBY POI / natural context:")
    if nearby_pois:
        for poi in nearby_pois[:5]:
            print(f"       • {format_poi_inline(poi)}")
    else:
        print("       • none")
    print(f"    🏷️ LINE 1 --> {line1}")
    print(f"    🏷️ LINE 2 --> {line2}")

    return {
        "image": image_path,
        "lat": lat,
        "lon": lon,
        "address": reverse_info,
        "address_en": reverse_info_en,
        "known_hint": known_hint,
        "here_place": here_place,
        "nearby_pois": nearby_pois,
        "line1": line1,
        "line2": line2,
        "watermark": f"{line1}\n{line2}",
    }


def _build_reverse_info_from_cached_context(
    location: Optional[Dict[str, Any]] = None,
    cached_geo: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a reverse-info shaped object from metadata/cache fields."""
    location = location or {}
    cached_geo = cached_geo or {}

    city = (cached_geo.get("city") or location.get("city") or "").strip()
    state = (cached_geo.get("state") or location.get("state") or "").strip()
    country = (cached_geo.get("country") or location.get("country") or "").strip()
    country_code = (
        (cached_geo.get("country_code") or location.get("country_code") or "").strip().lower()
    )
    road = (cached_geo.get("road") or "").strip()
    house_number = (cached_geo.get("house_number") or "").strip()

    address: Dict[str, Any] = {}
    if city:
        address["city"] = city
    if state:
        address["state"] = state
    if country:
        address["country"] = country
    if country_code:
        address["country_code"] = country_code
    if road:
        address["road"] = road
    if house_number:
        address["house_number"] = house_number

    name = (cached_geo.get("name") or location.get("name") or "").strip()
    display_name = (
        cached_geo.get("display_name")
        or location.get("formatted")
        or name
        or "Unknown location"
    )
    approximation = (
        name
        or road
        or city
        or str(display_name).split(",")[0].strip()
        or "Unknown location"
    )

    return {
        "name": name,
        "display_name": display_name,
        "approximation": approximation,
        "category": cached_geo.get("category", ""),
        "type": cached_geo.get("type", ""),
        "address": address,
        "namedetails": cached_geo.get("namedetails") or {},
        "extratags": cached_geo.get("extratags") or {},
    }


def build_watermark_from_cached_context(
    lat: Optional[float],
    lon: Optional[float],
    location: Optional[Dict[str, Any]] = None,
    cached_geo: Optional[Dict[str, Any]] = None,
    bilingual_output: bool = BILINGUAL_OUTPUT,
) -> Dict[str, Any]:
    """Build line1/line2 from cached geocode context without Overpass/Nominatim calls."""
    reverse_info = _build_reverse_info_from_cached_context(location=location, cached_geo=cached_geo)

    nearby_pois_raw = list((cached_geo or {}).get("nearby_pois") or [])
    nearby_pois: List[Dict[str, Any]] = []
    for poi in nearby_pois_raw:
        poi_type = (poi.get("type") or poi.get("category") or "").strip().lower()
        nearby_pois.append(
            {
                "name": poi.get("name"),
                "type": poi_type,
                "category": (poi.get("category") or "").strip().lower(),
                "distance_m": poi.get("distance_m"),
                "bearing_deg": poi.get("bearing_deg"),
                "bearing_cardinal": poi.get("bearing_cardinal"),
                "tags": poi.get("tags") or {},
            }
        )

    nearby_pois = select_watermark_pois(
        nearby_pois,
        max_distance_m=float(POI_FILTER_CONFIG.get("max_distance_m", 75)),
        limit=int(POI_FILTER_CONFIG.get("limit", 3)),
        allowed_categories=POI_FILTER_CONFIG.get("allowed_categories"),
        category_priority=POI_FILTER_CONFIG.get("category_priority"),
    )

    known_hint = None
    if lat is not None and lon is not None:
        known_hint = match_known_location_hint(lat, lon, reverse_info)

    if known_hint:
        nearby_pois = []

    here_place = derive_here_place(reverse_info, nearby_pois)
    line1, line2 = build_two_line_watermark(
        reverse_info,
        here_place,
        nearby_pois,
        known_hint=known_hint,
        line1_rule_config=LINE1_RULE_CONFIG,
    )

    # Bilingual translation in cached-only mode is intentionally skipped because
    # it would require an additional reverse-geocode request.
    if bilingual_output:
        line1 = format_bilingual(line1, "")
        line2 = format_bilingual(line2, "")

    if COPYRIGHT_STRING:
        line2 = f"{line2}  {COPYRIGHT_STRING}"

    return {
        "lat": lat,
        "lon": lon,
        "address": reverse_info,
        "known_hint": known_hint,
        "here_place": here_place,
        "nearby_pois": nearby_pois,
        "line1": line1,
        "line2": line2,
        "watermark": f"{line1}\n{line2}",
        "from_cache": True,
    }


# ---------------------------------------------------------------------------
# Batch folder processor
# ---------------------------------------------------------------------------

def process_folder(
    folder: str,
    style: str = "emoji",
    bilingual_output: bool = BILINGUAL_OUTPUT,
) -> List[Dict[str, Any]]:
    """Process all JPEG images in *folder* (recursive) and return results list."""
    patterns = ("**/*.jpg", "**/*.jpeg", "**/*.JPG", "**/*.JPEG")
    files = []
    for ext in patterns:
        files.extend(glob.glob(os.path.join(folder, ext), recursive=True))

    print(f"[DEBUG] Scanning folder (recursive): {folder}")
    print(f"[DEBUG] Found {len(files)} image files matching {patterns}")
    print(f"[DEBUG] Bilingual output: {'ON' if bilingual_output else 'OFF'}")

    results: List[Dict[str, Any]] = []
    for index, path in enumerate(sorted(files), start=1):
        print("\n" + "=" * 88)
        print(f"📸 PHOTO {index}/{len(files)}: {os.path.basename(path)}")
        print(f"    📁 {path}")
        print("-" * 88)
        info = process_photo(path, style=style, bilingual_output=bilingual_output)
        if info is None:
            print("    ⏭️ Skipped (processing failed)")
            continue
        if info.get("no_gps"):
            print(f"    📷 No GPS EXIF — copyright only: {info['line2']}")
        else:
            print(f"    ✅ RESULT: {info['line1']} | {info['line2']}")
        results.append(info)

    print(f"[DEBUG] Completed. Processed {len(results)} photos with valid GPS.")
    return results
