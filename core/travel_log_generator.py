#!/usr/bin/env python3
"""Generate album travel-log RAG JSON from master.json and geocode_cache.json.

The output is designed to prime an Ollama text model with chronological, geo-aware
photo context for travel-blog style writeups.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

from utils.config_utils import resolve_config_placeholders


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _safe_file_component(value: str) -> str:
    cleaned = str(value or "").strip().replace("/", "-").replace("\\", "-").replace(":", "-")
    cleaned = "-".join(part for part in cleaned.split() if part)
    return cleaned or "unknown"


def _parse_capture_time(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None

    v = value.strip()
    if not v:
        return None

    # ISO-ish variants first.
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        pass

    # EXIF DateTimeOriginal style.
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(v, fmt)
        except Exception:
            continue
    return None


def _normalized_dt_text(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return dt.isoformat()


def _format_utc_offset(delta: timedelta) -> Optional[str]:
    # Guard against outlier values from bad metadata.
    if abs(delta.total_seconds()) > (16 * 3600):
        return None

    total_minutes = int(round(delta.total_seconds() / 60.0))
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _infer_offset_from_capture_pair(dt_utc: Optional[datetime], dt_local: Optional[datetime]) -> Optional[str]:
    if dt_utc is None or dt_local is None:
        return None

    dt_utc_naive = dt_utc
    if dt_utc.tzinfo is not None:
        dt_utc_naive = dt_utc.astimezone(timezone.utc).replace(tzinfo=None)

    return _format_utc_offset(dt_local - dt_utc_naive)


def _compact_poi_search(poi_search: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key in ("attempted", "status", "result_count", "error"):
        if key in poi_search:
            compact[key] = poi_search.get(key)

    fallback_context = poi_search.get("fallback_context")
    if isinstance(fallback_context, dict):
        fallback_compact = {
            "summary": fallback_context.get("summary"),
            "anchor": fallback_context.get("anchor"),
            "formatted": fallback_context.get("formatted"),
            "display_name": fallback_context.get("display_name"),
            "type": fallback_context.get("type"),
            "provider": fallback_context.get("provider"),
        }
        if any(v is not None and v != "" for v in fallback_compact.values()):
            compact["fallback_context"] = fallback_compact

    return compact


def _compact_nearby_pois(nearby_pois: Any) -> List[Dict[str, Any]]:
    if not isinstance(nearby_pois, list):
        return []

    compact_items: List[Dict[str, Any]] = []
    for poi in nearby_pois:
        if not isinstance(poi, dict):
            continue
        compact_items.append(
            {
                "name": poi.get("name"),
                "category": poi.get("category"),
                "distance_m": poi.get("distance_m"),
                "bearing_deg": poi.get("bearing_deg"),
                "bearing_cardinal": poi.get("bearing_cardinal"),
            }
        )
    return compact_items


def _join_list(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    return "\n".join(f"- {v}" for v in cleaned)


def _sample_entries_uniform(entries: List[Dict[str, Any]], max_entries: int) -> List[Dict[str, Any]]:
    if max_entries <= 0:
        return []
    if len(entries) <= max_entries:
        return entries
    if max_entries == 1:
        return [entries[-1]]

    n = len(entries)
    picked: set[int] = {0, n - 1}
    for i in range(1, max_entries - 1):
        idx = round(i * (n - 1) / (max_entries - 1))
        picked.add(max(0, min(n - 1, idx)))
    return [entries[i] for i in sorted(picked)]


def _entry_for_story_prompt(entry: Dict[str, Any], max_photos: int, max_pois: int) -> Dict[str, Any]:
    geocode_cache = entry.get("geocode_cache") if isinstance(entry.get("geocode_cache"), dict) else {}
    location = entry.get("location") if isinstance(entry.get("location"), dict) else {}
    gps = entry.get("gps") if isinstance(entry.get("gps"), dict) else {}

    photos = geocode_cache.get("photos") if isinstance(geocode_cache.get("photos"), list) else []
    nearby_pois = geocode_cache.get("nearby_pois") if isinstance(geocode_cache.get("nearby_pois"), list) else []
    poi_search = geocode_cache.get("poi_search") if isinstance(geocode_cache.get("poi_search"), dict) else {}

    compact_poi = []
    for poi in nearby_pois[:max(0, max_pois)]:
        if not isinstance(poi, dict):
            continue
        compact_poi.append(
            {
                "name": poi.get("name"),
                "category": poi.get("category"),
                "distance_m": poi.get("distance_m"),
                "bearing_cardinal": poi.get("bearing_cardinal"),
            }
        )

    return {
        "sequence": entry.get("sequence"),
        "file_name": entry.get("file_name"),
        "album_name": entry.get("album_name"),
        "captured_at_utc": entry.get("captured_at_utc"),
        "captured_at_local": entry.get("captured_at_local"),
        "gps": {
            "lat": gps.get("lat"),
            "lon": gps.get("lon"),
            "cardinal": gps.get("cardinal"),
        },
        "location": {
            "formatted": location.get("formatted"),
            "city": location.get("city"),
            "state": location.get("state"),
            "country": location.get("country"),
        },
        "high_level_summary": entry.get("high_level_summary"),
        "geocode_cache": {
            "photos": photos[:max(0, max_photos)],
            "nearby_pois": compact_poi,
            "poi_search": {
                "status": poi_search.get("status"),
                "result_count": poi_search.get("result_count"),
                "fallback_context": poi_search.get("fallback_context"),
            },
        },
    }


def _build_story_prompt_payload(
    rag_payload: Dict[str, Any],
    max_entries: int,
    max_photos_per_entry: int,
    max_pois_per_entry: int,
) -> Dict[str, Any]:
    root = rag_payload.get("travel_log_rag") if isinstance(rag_payload.get("travel_log_rag"), dict) else {}
    entries = root.get("entries") if isinstance(root.get("entries"), list) else []

    sampled = _sample_entries_uniform(entries, max_entries=max_entries)
    compact_entries = [
        _entry_for_story_prompt(
            e,
            max_photos=max_photos_per_entry,
            max_pois=max_pois_per_entry,
        )
        for e in sampled
        if isinstance(e, dict)
    ]

    return {
        "travel_log_rag": {
            "generated_at": root.get("generated_at"),
            "album_filter": root.get("album_filter"),
            "summary": root.get("summary"),
            "entries_total": len(entries),
            "entries_in_prompt": len(compact_entries),
            "entries": compact_entries,
        }
    }


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _fmt_coord(value: Optional[float]) -> str:
    if value is None:
        return "not available"
    return f"{value:.6f}"


def _derive_map_scope_context(rag_payload: Dict[str, Any]) -> Dict[str, str]:
    root = rag_payload.get("travel_log_rag") if isinstance(rag_payload.get("travel_log_rag"), dict) else {}
    entries = root.get("entries") if isinstance(root.get("entries"), list) else []

    coords: List[Tuple[float, float]] = []
    city_counts: Counter[str] = Counter()
    road_counts: Counter[str] = Counter()
    poi_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    country_counts: Counter[str] = Counter()
    city_coords: Dict[str, List[Tuple[float, float]]] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        gps = entry.get("gps") if isinstance(entry.get("gps"), dict) else {}
        lat = _safe_float(gps.get("lat"))
        lon = _safe_float(gps.get("lon"))
        has_coord = lat is not None and lon is not None
        if has_coord:
            coords.append((lat, lon))

        location = entry.get("location") if isinstance(entry.get("location"), dict) else {}
        city = str(location.get("city") or "").strip()
        if city:
            city_counts[city] += 1
            if has_coord:
                city_coords.setdefault(city, []).append((lat, lon))

        state = str(location.get("state") or "").strip()
        if state:
            state_counts[state] += 1

        country = str(location.get("country") or "").strip()
        if country:
            country_counts[country] += 1

        road = str(location.get("road") or "").strip()
        if road:
            road_counts[road] += 1

        geo_cache = entry.get("geocode_cache") if isinstance(entry.get("geocode_cache"), dict) else {}
        nearby = geo_cache.get("nearby_pois") if isinstance(geo_cache.get("nearby_pois"), list) else []
        for poi in nearby:
            if not isinstance(poi, dict):
                continue
            name = str(poi.get("name") or "").strip()
            if name:
                poi_counts[name] += 1

    north = south = east = west = None
    lat_span = lon_span = 0.0
    if coords:
        lats = [c[0] for c in coords]
        lons = [c[1] for c in coords]
        north = max(lats)
        south = min(lats)
        east = max(lons)
        west = min(lons)
        lat_span = north - south
        lon_span = east - west

    top_cities = [name for name, _ in city_counts.most_common(5)]
    top_roads = [name for name, _ in road_counts.most_common(8)]
    top_pois = [name for name, _ in poi_counts.most_common(12)]

    if top_cities and (lat_span > 0.20 or lon_span > 0.20 or len(top_cities) > 1):
        map_subject = f"Full RAG region overview map covering {', '.join(top_cities)}"
        scope_recommendation = "Use a regional overview framing with simplified but anchored POI placement."
    elif top_cities:
        map_subject = f"{top_cities[0]} POI cluster map"
        scope_recommendation = "Use a dense local framing with higher POI detail and tighter scale."
    else:
        map_subject = "Full RAG region overview map"
        scope_recommendation = "Use an overview framing anchored to GPS extent only."

    scope_lines: List[str] = []
    if coords:
        scope_lines.append(
            "1. Full RAG Region Map: "
            f"N {_fmt_coord(north)}, S {_fmt_coord(south)}, W {_fmt_coord(west)}, E {_fmt_coord(east)}"
        )
    else:
        scope_lines.append("1. Full RAG Region Map: GPS bounds not available in RAG")

    for idx, city_name in enumerate(top_cities[:4], start=2):
        ccoords = city_coords.get(city_name, [])
        if ccoords:
            clats = [c[0] for c in ccoords]
            clons = [c[1] for c in ccoords]
            scope_lines.append(
                f"{idx}. {city_name} Cluster: "
                f"N {_fmt_coord(max(clats))}, S {_fmt_coord(min(clats))}, "
                f"W {_fmt_coord(min(clons))}, E {_fmt_coord(max(clons))}"
            )
        else:
            scope_lines.append(f"{idx}. {city_name} Cluster: bounds not available")

    top_state = state_counts.most_common(1)[0][0] if state_counts else ""
    top_country = country_counts.most_common(1)[0][0] if country_counts else ""

    location_phrase = ", ".join(filter(None, [top_state, top_country])) or "an unknown region"

    if top_cities and coords:
        city_list = ", ".join(top_cities[:3])
        geographic_summary = (
            f"A map of {city_list} in {location_phrase}, "
            f"bounded by north {_fmt_coord(north)}\u00b0, south {_fmt_coord(south)}\u00b0, "
            f"west {_fmt_coord(west)}\u00b0, east {_fmt_coord(east)}\u00b0."
        )
    elif coords:
        geographic_summary = (
            f"A map of {location_phrase}, "
            f"bounded by north {_fmt_coord(north)}\u00b0, south {_fmt_coord(south)}\u00b0, "
            f"west {_fmt_coord(west)}\u00b0, east {_fmt_coord(east)}\u00b0."
        )
    else:
        geographic_summary = "Geographic bounds not available in RAG."

    return {
        "map_subject": map_subject,
        "scope_recommendation": scope_recommendation,
        "geographic_summary": geographic_summary,
        "bbox_north": _fmt_coord(north),
        "bbox_south": _fmt_coord(south),
        "bbox_west": _fmt_coord(west),
        "bbox_east": _fmt_coord(east),
        "scope_options": "\n".join(scope_lines),
        "anchor_cities": ", ".join(top_cities) if top_cities else "Not present in RAG",
        "anchor_roads": ", ".join(top_roads) if top_roads else "Not present in RAG",
        "anchor_pois": ", ".join(top_pois) if top_pois else "Not present in RAG",
    }


def _resolve_map_label_policy(map_cfg: Dict[str, Any]) -> str:
    raw = str(map_cfg.get("label_policy") or "cities_and_pois").strip().lower()
    if raw in {"a", "none", "off", "no_labels"}:
        return "No labels. Use iconography only."
    if raw in {"b", "cities", "cities_only"}:
        return "Labels ON for cities only."
    if raw in {"c", "cities_and_pois", "cities+pois", "cities_pois"}:
        return "Labels ON for cities and POIs present in RAG."
    if raw in {"d", "all", "all_allowed_by_rag"}:
        return "Labels ON for all features explicitly present in RAG."
    return str(map_cfg.get("label_policy") or "Labels ON for cities and POIs present in RAG.")


def _resolve_map_target_model(map_cfg: Dict[str, Any]) -> Tuple[str, str]:
    raw = str(map_cfg.get("target_model") or "openai").strip().lower()
    aliases = {
        "openai": "openai",
        "dalle": "openai",
        "dall-e": "openai",
        "generic": "openai",
        "sdxl": "sdxl",
        "stable-diffusion-xl": "sdxl",
        "midjourney": "midjourney",
        "mj": "midjourney",
    }
    if raw not in aliases:
        raise ValueError(
            "Invalid travel_map_generation.target_model="
            f"'{raw}'. Allowed values: openai, sdxl, midjourney "
            "(aliases: dalle, dall-e, generic, stable-diffusion-xl, mj)."
        )
    target = aliases[raw]

    if target == "sdxl":
        return (
            "SDXL",
            "Return exactly this structure for Section 1:\n"
            "- `### SDXL Prompt`\n"
            "- `Positive:` one detailed SDXL-positive prompt paragraph\n"
            "- `Negative:` one SDXL-negative prompt line suppressing artifacts, hallucinated geography, and label clutter\n"
            "Do not include OpenAI or Midjourney variants.",
        )

    if target == "midjourney":
        return (
            "Midjourney",
            "Return exactly this structure for Section 1:\n"
            "- `### Midjourney Prompt`\n"
            "- `Prompt:` one descriptor-first Midjourney prompt line that begins exactly with `Prompt: Create an isometric travel map ...`\n"
            "- `Parameters:` one line including `--ar`, `--stylize`, `--chaos`, `--quality`, `--v`, and `--no`\n"
            "The Midjourney prompt line must explicitly include both cues exactly:\n"
            "- `Maintain consistent isometric scale across all POI icons and terrain features.`\n"
            "- `Foreground coastline -> midground towns -> background ridges and highlands.`\n"
            "Include no other provider variants.",
        )

    return (
        "OpenAI",
        "Return exactly this structure for Section 1:\n"
        "- `### OpenAI Prompt`\n"
        "- One production-ready paragraph prompt for OpenAI image generation\n"
        "Do not include SDXL or Midjourney variants.",
    )


def _validate_resolved_map_prompt(
    prompt_text: str,
    map_cfg: Dict[str, Any],
    scope_context: Dict[str, str],
    template_path: Path,
    request_path: Path,
) -> None:
    target_label, _ = _resolve_map_target_model(map_cfg)
    target = target_label.strip().lower()
    issues: List[str] = []

    if "# Navigium Map Prompt" not in prompt_text:
        issues.append("Missing required heading '# Navigium Map Prompt'.")

    primary_style = str(map_cfg.get("artist_style") or "").strip()
    if primary_style and primary_style not in prompt_text:
        issues.append(f"Missing primary artist style reference '{primary_style}'.")

    for key in ("bbox_north", "bbox_south", "bbox_west", "bbox_east"):
        value = str(scope_context.get(key) or "").strip()
        if value and value not in prompt_text:
            issues.append(f"Missing resolved bounding value {key}={value} in output.")

    if target == "midjourney":
        for required in (
            "### Midjourney Prompt",
            "Parameters:",
            "Maintain consistent isometric scale across all POI icons and terrain features.",
            "Foreground coastline -> midground towns -> background ridges and highlands.",
            "--ar",
            "--v",
            "--no",
        ):
            if required not in prompt_text:
                issues.append(f"Missing Midjourney contract token: '{required}'.")
        if "Prompt: Create " not in prompt_text:
            issues.append("Missing imperative command prefix: Midjourney prompt must start with 'Prompt: Create ...'.")
    elif target == "sdxl":
        for required in ("### SDXL Prompt", "Positive:", "Negative:"):
            if required not in prompt_text:
                issues.append(f"Missing SDXL contract token: '{required}'.")
    elif target == "openai":
        if "### OpenAI Prompt" not in prompt_text:
            issues.append("Missing OpenAI contract token: '### OpenAI Prompt'.")

    if not issues:
        return

    issues_text = "\n".join(f"- {item}" for item in issues)
    raise ValueError(
        "Resolved map prompt is out of sync with template contract.\n"
        f"Target model: {target_label}\n"
        f"Template: {template_path}\n"
        f"Request prompt: {request_path}\n"
        "Why it failed:\n"
        f"{issues_text}\n"
        "Recourse:\n"
        "- Fix the map prompt template contract in config/travel_map_prompt_template.md.\n"
        "- Verify travel_map_generation.target_model in config/pipeline_config.json.\n"
        "- Re-run map prompt generation after correcting required sections/tokens."
    )


def _repair_midjourney_contract(prompt_text: str, map_cfg: Dict[str, Any]) -> str:
    repaired = prompt_text
    primary_style = str(map_cfg.get("artist_style") or "").strip()

    # Ensure required cues appear in the Midjourney prompt body even if model omitted them.
    required_phrases = [
        "Maintain consistent isometric scale across all POI icons and terrain features.",
        "Foreground coastline -> midground towns -> background ridges and highlands.",
    ]
    if primary_style:
        required_phrases.append(f"Primary style: {primary_style}.")

    prompt_anchor = "Prompt:"
    if prompt_anchor in repaired:
        start = repaired.find(prompt_anchor)
        line_end = repaired.find("\n", start)
        if line_end == -1:
            line_end = len(repaired)
        prompt_line = repaired[start:line_end]

        if not prompt_line.startswith("Prompt: Create "):
            if prompt_line.startswith("Prompt: "):
                prompt_line = "Prompt: Create " + prompt_line[len("Prompt: "):].lstrip()
            else:
                prompt_line = "Prompt: Create an isometric travel map. " + prompt_line

        missing = [p for p in required_phrases if p not in repaired]
        if missing:
            prompt_line = prompt_line.rstrip() + " " + " ".join(missing)
        repaired = repaired[:start] + prompt_line + repaired[line_end:]
    else:
        repaired = repaired.rstrip() + "\n\nPrompt: Create an isometric travel map."
        missing = [p for p in required_phrases if p not in repaired]
        if missing:
            repaired = repaired.rstrip() + " " + " ".join(missing)

    return repaired


def _repair_resolved_map_prompt(prompt_text: str, map_cfg: Dict[str, Any]) -> str:
    target_label, _ = _resolve_map_target_model(map_cfg)
    target = target_label.strip().lower()
    if target == "midjourney":
        return _repair_midjourney_contract(prompt_text, map_cfg)
    return prompt_text


def _format_story_prompt(
    template: str,
    story_cfg: Dict[str, Any],
    rag_payload: Dict[str, Any],
) -> str:
    rag_json = json.dumps(rag_payload, ensure_ascii=False, indent=2)

    replacements = {
        "persona": str(story_cfg.get("persona") or "Travel storyteller and cultural editor"),
        "positive_guidance": _join_list(story_cfg.get("positive_guidance")),
        "negative_guidance": _join_list(story_cfg.get("negative_guidance")),
        "style_guide": str(story_cfg.get("style_guide") or "Concise, vivid, factual, and grounded in metadata"),
        "format_guide": str(story_cfg.get("format_guide") or "Return valid Markdown with headings, highlights, and tasteful emoji"),
        "rag_json": rag_json,
    }

    prompt = template
    for key, value in replacements.items():
        prompt = prompt.replace("{" + key + "}", value)

    return prompt


def _format_map_prompt(
    template: str,
    story_cfg: Dict[str, Any],
    map_cfg: Dict[str, Any],
    rag_payload: Dict[str, Any],
    scope_context: Dict[str, str],
) -> str:
    rag_json = json.dumps(rag_payload, ensure_ascii=False, indent=2)
    map_width = int(map_cfg.get("image_width") or 800)
    map_height = int(map_cfg.get("image_height") or 800)
    target_label, target_requirements = _resolve_map_target_model(map_cfg)

    replacements = {
        "persona": str(story_cfg.get("persona") or "Travel storyteller and cultural editor"),
        "positive_guidance": _join_list(story_cfg.get("positive_guidance")),
        "negative_guidance": _join_list(story_cfg.get("negative_guidance")),
        "style_guide": str(story_cfg.get("style_guide") or "Concise, vivid, factual, and grounded in metadata"),
        "format_guide": str(story_cfg.get("format_guide") or "Return valid Markdown with headings and highlights"),
        "map_width": str(map_width),
        "map_height": str(map_height),
        "artist_style": str(map_cfg.get("artist_style") or "Durer"),
        "artist_style_list": str(map_cfg.get("artist_style_list") or "Piranesi, Merian, Moebius, Nicolas Delort, Ian McQue"),
        "style_brief": str(
            (map_cfg.get("artist_style_briefs") or {}).get(
                str(map_cfg.get("artist_style") or ""), ""
            ) or map_cfg.get("style_brief") or ""
        ),
        "geographic_summary": str(scope_context.get("geographic_summary") or "Geographic bounds not available in RAG."),
        "map_subject": str(scope_context.get("map_subject") or "Full RAG region overview map"),
        "scope_recommendation": str(scope_context.get("scope_recommendation") or "Use an overview framing anchored to GPS extent."),
        "bbox_north": str(scope_context.get("bbox_north") or "not available"),
        "bbox_south": str(scope_context.get("bbox_south") or "not available"),
        "bbox_west": str(scope_context.get("bbox_west") or "not available"),
        "bbox_east": str(scope_context.get("bbox_east") or "not available"),
        "scope_options": str(scope_context.get("scope_options") or "1. Full RAG Region Map: bounds not available"),
        "anchor_cities": str(scope_context.get("anchor_cities") or "Not present in RAG"),
        "anchor_roads": str(scope_context.get("anchor_roads") or "Not present in RAG"),
        "anchor_pois": str(scope_context.get("anchor_pois") or "Not present in RAG"),
        "map_label_policy": _resolve_map_label_policy(map_cfg),
        "map_target_model": target_label,
        "map_target_requirements": target_requirements,
        "rag_json": rag_json,
    }

    prompt = template
    for key, value in replacements.items():
        prompt = prompt.replace("{" + key + "}", value)

    return prompt


def _load_prompt_template(template_path: Path) -> str:
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


def generate_travel_story_markdown(
    config: Dict[str, Any],
    rag_payload: Dict[str, Any],
    output_dir: Path,
    output_album: str,
) -> Path:
    llm_cfg = config.get("llm_image_analysis", {}) if isinstance(config.get("llm_image_analysis"), dict) else {}
    story_cfg = config.get("travel_story_generation", {}) if isinstance(config.get("travel_story_generation"), dict) else {}

    endpoint = str(story_cfg.get("endpoint") or llm_cfg.get("endpoint") or "http://localhost:11434").rstrip("/")
    model = str(story_cfg.get("model") or llm_cfg.get("model") or "gemma4:latest")
    timeout_seconds = int(story_cfg.get("timeout_seconds") or 120)

    template_path = Path(str(story_cfg.get("prompt_template") or "config/travel_story_prompt_template.md"))
    if not template_path.is_absolute():
        template_path = Path.cwd() / template_path
    if not template_path.exists():
        raise FileNotFoundError(f"travel story prompt template not found: {template_path}")

    template = _load_prompt_template(template_path)
    prompt_max_chars = int(story_cfg.get("prompt_max_chars") or 32000)
    min_entries = max(1, int(story_cfg.get("prompt_min_entries") or 24))
    max_entries = max(min_entries, int(story_cfg.get("prompt_max_entries") or 160))
    max_photos = max(0, int(story_cfg.get("prompt_max_photos_per_entry") or 5))
    max_pois = max(0, int(story_cfg.get("prompt_max_pois_per_entry") or 3))

    working_max_entries = max_entries
    log.info(
        "Building story prompt: max_entries=%d, min_entries=%d, max_chars=%d",
        working_max_entries, min_entries, prompt_max_chars,
    )
    prompt_payload = _build_story_prompt_payload(
        rag_payload=rag_payload,
        max_entries=working_max_entries,
        max_photos_per_entry=max_photos,
        max_pois_per_entry=max_pois,
    )
    prompt = _format_story_prompt(template, story_cfg, prompt_payload)
    log.info("Initial prompt size: %d chars (%d entries)", len(prompt), working_max_entries)

    compaction_rounds = 0
    while len(prompt) > prompt_max_chars and working_max_entries > min_entries:
        next_limit = max(min_entries, int(working_max_entries * 0.85))
        if next_limit == working_max_entries:
            next_limit = working_max_entries - 1
        working_max_entries = max(min_entries, next_limit)
        compaction_rounds += 1
        log.info(
            "  Compacting prompt (round %d): reducing to %d entries …",
            compaction_rounds, working_max_entries,
        )
        prompt_payload = _build_story_prompt_payload(
            rag_payload=rag_payload,
            max_entries=working_max_entries,
            max_photos_per_entry=max_photos,
            max_pois_per_entry=max_pois,
        )
        prompt = _format_story_prompt(template, story_cfg, prompt_payload)
        log.info("  Prompt size after round %d: %d chars", compaction_rounds, len(prompt))

    if len(prompt) > prompt_max_chars:
        log.warning(
            "Prompt still %d chars after entry compaction (limit %d). "
            "Attempting ultra-compact mode (min_entries=%d, no photos, 1 POI) …",
            len(prompt), prompt_max_chars, min_entries,
        )
        ultra_pois = 1 if max_pois > 0 else 0
        prompt_payload = _build_story_prompt_payload(
            rag_payload=rag_payload,
            max_entries=min_entries,
            max_photos_per_entry=0,
            max_pois_per_entry=ultra_pois,
        )
        prompt = _format_story_prompt(template, story_cfg, prompt_payload)
        log.info("Ultra-compact prompt size: %d chars", len(prompt))

    if len(prompt) > prompt_max_chars:
        log.warning(
            "Prompt is %d chars — still exceeds prompt_max_chars=%d after all compaction stages. "
            "Proceeding with truncated prompt. Increase prompt_max_chars in config to avoid data loss.",
            len(prompt), prompt_max_chars,
        )
        prompt = prompt[:prompt_max_chars]
    else:
        log.info("Final prompt size: %d chars — within limit.", len(prompt))

    safe_album = _safe_file_component(output_album or "all_albums")
    safe_model = _safe_file_component(model)

    prompt_name_template = str(story_cfg.get("resolved_prompt_name") or "{album}-Adventum-prompt.md")
    prompt_name = prompt_name_template.replace("{album}", safe_album).replace("{model}", safe_model)
    prompt_path = output_dir / prompt_name
    _save_text(prompt_path, prompt)
    prompt = prompt_path.read_text(encoding="utf-8")

    request_payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": float(story_cfg.get("temperature") or 0.6),
            "top_p": float(story_cfg.get("top_p") or 0.9),
            "num_predict": int(story_cfg.get("max_tokens") or 2200),
        },
    }

    response = requests.post(
        f"{endpoint}/api/generate",
        json=request_payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    raw = response.json().get("response", "")
    text = str(raw).strip()

    story_name_template = str(story_cfg.get("output_name") or "{album}-Adventum-{model}.md")
    story_name = story_name_template.replace("{album}", safe_album).replace("{model}", safe_model)
    if not story_name.lower().endswith(".md"):
        story_name = f"{story_name}.md"
    story_path = output_dir / story_name

    prepend_album_title = bool(story_cfg.get("prepend_album_title", False))
    if prepend_album_title and not text.lstrip().startswith("#"):
        text = f"# {output_album} Travel Story\n\n{text}"

    legacy_story_path = output_dir / f"{safe_album}.md"
    if legacy_story_path.exists() and legacy_story_path != story_path:
        legacy_story_path.unlink()

    legacy_prompt_path = output_dir / "travel_story_prompt_resolved.md"
    if legacy_prompt_path.exists() and legacy_prompt_path != prompt_path:
        legacy_prompt_path.unlink()

    legacy_llmrag_prompt_path = output_dir / f"{safe_album}-LLMRAG_prompt.md"
    if legacy_llmrag_prompt_path.exists() and legacy_llmrag_prompt_path != prompt_path:
        legacy_llmrag_prompt_path.unlink()

    for obsolete_name in (
        f"{safe_album}-map.png",
        f"{safe_album}-map-notes.md",
        f"{safe_album}-map-prompt.md",
    ):
        obsolete_path = output_dir / obsolete_name
        if obsolete_path.exists():
            obsolete_path.unlink()

    _save_text(story_path, text + "\n")
    return story_path


def generate_travel_map_prompt_markdown(
    config: Dict[str, Any],
    rag_payload: Dict[str, Any],
    output_dir: Path,
    output_album: str,
) -> Path:
    llm_cfg = config.get("llm_image_analysis", {}) if isinstance(config.get("llm_image_analysis"), dict) else {}
    story_cfg = config.get("travel_story_generation", {}) if isinstance(config.get("travel_story_generation"), dict) else {}
    map_cfg = config.get("travel_map_generation", {}) if isinstance(config.get("travel_map_generation"), dict) else {}

    endpoint = str(map_cfg.get("endpoint") or story_cfg.get("endpoint") or llm_cfg.get("endpoint") or "http://localhost:11434").rstrip("/")
    model = str(map_cfg.get("model") or story_cfg.get("model") or llm_cfg.get("model") or "gemma4:latest")
    timeout_seconds = int(map_cfg.get("timeout_seconds") or story_cfg.get("timeout_seconds") or 120)
    resolve_with_local_llm = bool(map_cfg.get("resolve_with_local_llm", True))
    save_request_prompt = bool(map_cfg.get("save_request_prompt", True))
    strict_sync = bool(map_cfg.get("strict_sync", False))

    template_path = Path(str(map_cfg.get("prompt_template") or "config/travel_map_prompt_template.md"))
    if not template_path.is_absolute():
        template_path = Path.cwd() / template_path
    if not template_path.exists():
        raise FileNotFoundError(f"travel map prompt template not found: {template_path}")

    template = _load_prompt_template(template_path)
    scope_context = _derive_map_scope_context(rag_payload)
    prompt_max_chars = int(map_cfg.get("prompt_max_chars") or story_cfg.get("prompt_max_chars") or 64000)
    min_entries = max(1, int(map_cfg.get("prompt_min_entries") or story_cfg.get("prompt_min_entries") or 24))
    max_entries = max(min_entries, int(map_cfg.get("prompt_max_entries") or story_cfg.get("prompt_max_entries") or 160))
    max_photos = max(0, int(map_cfg.get("prompt_max_photos_per_entry") or story_cfg.get("prompt_max_photos_per_entry") or 5))
    max_pois = max(0, int(map_cfg.get("prompt_max_pois_per_entry") or story_cfg.get("prompt_max_pois_per_entry") or 3))

    working_max_entries = max_entries
    log.info(
        "Building map prompt: max_entries=%d, min_entries=%d, max_chars=%d, image=%sx%s",
        working_max_entries,
        min_entries,
        prompt_max_chars,
        int(map_cfg.get("image_width") or 800),
        int(map_cfg.get("image_height") or 800),
    )
    prompt_payload = _build_story_prompt_payload(
        rag_payload=rag_payload,
        max_entries=working_max_entries,
        max_photos_per_entry=max_photos,
        max_pois_per_entry=max_pois,
    )
    request_prompt = _format_map_prompt(template, story_cfg, map_cfg, prompt_payload, scope_context)
    log.info("Initial map request prompt size: %d chars (%d entries)", len(request_prompt), working_max_entries)

    compaction_rounds = 0
    while len(request_prompt) > prompt_max_chars and working_max_entries > min_entries:
        next_limit = max(min_entries, int(working_max_entries * 0.85))
        if next_limit == working_max_entries:
            next_limit = working_max_entries - 1
        working_max_entries = max(min_entries, next_limit)
        compaction_rounds += 1
        log.info(
            "  Compacting map prompt (round %d): reducing to %d entries ...",
            compaction_rounds,
            working_max_entries,
        )
        prompt_payload = _build_story_prompt_payload(
            rag_payload=rag_payload,
            max_entries=working_max_entries,
            max_photos_per_entry=max_photos,
            max_pois_per_entry=max_pois,
        )
        request_prompt = _format_map_prompt(template, story_cfg, map_cfg, prompt_payload, scope_context)
        log.info("  Map request prompt size after round %d: %d chars", compaction_rounds, len(request_prompt))

    if len(request_prompt) > prompt_max_chars:
        log.warning(
            "Map request prompt still %d chars after entry compaction (limit %d). "
            "Attempting ultra-compact mode (min_entries=%d, no photos, 1 POI) ...",
            len(request_prompt), prompt_max_chars, min_entries,
        )
        ultra_pois = 1 if max_pois > 0 else 0
        prompt_payload = _build_story_prompt_payload(
            rag_payload=rag_payload,
            max_entries=min_entries,
            max_photos_per_entry=0,
            max_pois_per_entry=ultra_pois,
        )
        request_prompt = _format_map_prompt(template, story_cfg, map_cfg, prompt_payload, scope_context)
        log.info("Ultra-compact map request prompt size: %d chars", len(request_prompt))

    if len(request_prompt) > prompt_max_chars:
        log.warning(
            "Map request prompt is %d chars and exceeds prompt_max_chars=%d after compaction. "
            "Proceeding with truncated request prompt.",
            len(request_prompt), prompt_max_chars,
        )
        request_prompt = request_prompt[:prompt_max_chars]
    else:
        log.info("Final map request prompt size: %d chars - within limit.", len(request_prompt))

    safe_album = _safe_file_component(output_album or "all_albums")
    safe_model = _safe_file_component(model)

    request_name_template = str(map_cfg.get("request_output_name") or "{album}-navigium-request.md")
    request_name = request_name_template.replace("{album}", safe_album).replace("{model}", safe_model)
    request_path = output_dir / request_name
    if save_request_prompt:
        _save_text(request_path, request_prompt)

    final_prompt = request_prompt
    if resolve_with_local_llm:
        log.info("Resolving map request prompt via local Ollama model=%s", model)
        request_payload: Dict[str, Any] = {
            "model": model,
            "prompt": request_prompt,
            "stream": False,
            "options": {
                "temperature": float(map_cfg.get("temperature") or 0.3),
                "top_p": float(map_cfg.get("top_p") or 0.9),
                "num_predict": int(map_cfg.get("max_tokens") or 2600),
            },
        }
        try:
            response = requests.post(
                f"{endpoint}/api/generate",
                json=request_payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            resolved = str(response.json().get("response", "")).strip()
            if not resolved:
                raise ValueError("empty response from local map prompt resolver")
            final_prompt = resolved
            log.info("Resolved map prompt via local Ollama (%d chars)", len(final_prompt))
            try:
                _validate_resolved_map_prompt(
                    prompt_text=final_prompt,
                    map_cfg=map_cfg,
                    scope_context=scope_context,
                    template_path=template_path,
                    request_path=request_path,
                )
            except ValueError as sync_exc:
                repaired_prompt = _repair_resolved_map_prompt(final_prompt, map_cfg)
                if repaired_prompt != final_prompt:
                    final_prompt = repaired_prompt
                    log.warning(
                        "Resolved map prompt was out of sync; applied automatic contract repair before final validation."
                    )
                try:
                    _validate_resolved_map_prompt(
                        prompt_text=final_prompt,
                        map_cfg=map_cfg,
                        scope_context=scope_context,
                        template_path=template_path,
                        request_path=request_path,
                    )
                except ValueError as final_sync_exc:
                    details = (
                        "Map prompt remains out of sync after auto-repair. "
                        f"Template: {template_path}. Request prompt: {request_path}. "
                        f"Cause: {final_sync_exc}"
                    )
                    if strict_sync:
                        raise RuntimeError(details)
                    log.warning(
                        "%s. strict_sync=false, continuing with last resolved prompt. "
                        "Recourse: inspect request prompt, fix template/config mismatch, and rerun.",
                        details,
                    )
        except Exception as exc:
            if strict_sync:
                raise RuntimeError(
                    "Map prompt resolution failed and strict sync is enabled. "
                    f"Cause: {exc}. "
                    f"Endpoint: {endpoint}. Model: {model}. "
                    "Recourse: inspect request prompt, fix template/config mismatch, and rerun."
                )
            log.warning(
                "Map prompt resolution issue encountered: %s. Endpoint: %s. Model: %s. "
                "strict_sync=false, continuing with request prompt fallback. "
                "Recourse: inspect request prompt, fix template/config mismatch, and rerun.",
                exc,
                endpoint,
                model,
            )
            final_prompt = request_prompt

    prompt_name_template = str(map_cfg.get("prompt_output_name") or "{album}-navigium-prompt.md")
    prompt_name = prompt_name_template.replace("{album}", safe_album).replace("{model}", safe_model)
    prompt_path = output_dir / prompt_name
    _save_text(prompt_path, final_prompt)

    return prompt_path


def _is_source_entry(key: str, raw_root: Path) -> bool:
    raw_prefix = str(raw_root.resolve()) + "/"
    return str(key).startswith(raw_prefix)


def _get_geocode_entry(
    entry: Dict[str, Any],
    geocode_cache: Dict[str, Any],
    geocode_by_photo: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[str], Dict[str, Any]]:
    gps = entry.get("gps") if isinstance(entry.get("gps"), dict) else {}
    lat = gps.get("lat")
    lon = gps.get("lon")

    try:
        if lat is not None and lon is not None:
            key = f"{float(lat):.6f},{float(lon):.6f}"
            match = geocode_cache.get(key)
            if isinstance(match, dict):
                return key, match
    except Exception:
        pass

    file_name = str(entry.get("file_name") or "").strip()
    if file_name and file_name in geocode_by_photo:
        return None, geocode_by_photo[file_name]

    return None, {}


def generate_travel_log_from_config(
    config_path: str = "config/pipeline_config.json",
    album: Optional[str] = None,
    output_name: Optional[str] = None,
) -> Path:
    cfg = resolve_config_placeholders(_load_json(Path(config_path)))
    tl_cfg = cfg.get("travel_log_generation", {}) if isinstance(cfg.get("travel_log_generation"), dict) else {}
    name_template = output_name or str(tl_cfg.get("rag_output_name") or "{album}-LLMRAG-data.json")
    resolved_album = str(album).strip() if album else "all_albums"
    resolved_output_name = name_template.replace("{album}", resolved_album)
    paths = cfg.get("paths", {}) if isinstance(cfg, dict) else {}

    raw_root = Path(paths.get("raw_input", "")).resolve()
    pipeline_base = Path(paths.get("pipeline_base", "")).resolve()
    metadata_dir = Path(paths.get("metadata_dir", "")).resolve()
    master_path = Path(paths.get("master_catalog", "")).resolve()
    geocode_path = metadata_dir / "geocode_cache.json"

    if not master_path.exists():
        raise FileNotFoundError(f"master.json not found: {master_path}")

    geocode_cache: Dict[str, Any] = {}
    if geocode_path.exists():
        loaded_geocode = _load_json(geocode_path)
        if isinstance(loaded_geocode, dict):
            geocode_cache = loaded_geocode

    master_data = _load_json(master_path)
    if not isinstance(master_data, dict):
        raise ValueError("master.json must be a top-level JSON object")

    geocode_by_photo: Dict[str, Dict[str, Any]] = {}
    for _, geo_entry in geocode_cache.items():
        if not isinstance(geo_entry, dict):
            continue
        photos = geo_entry.get("photos")
        if not isinstance(photos, list):
            continue
        for name in photos:
            if isinstance(name, str) and name and name not in geocode_by_photo:
                geocode_by_photo[name] = geo_entry

    album_filter = str(album).strip() if album else None
    items: List[Dict[str, Any]] = []

    for source_key, entry in master_data.items():
        if not isinstance(source_key, str) or not isinstance(entry, dict):
            continue
        if not _is_source_entry(source_key, raw_root):
            continue

        album_name = str(entry.get("album_name") or Path(source_key).parent.name)
        if album_filter and album_name != album_filter:
            continue

        dt_utc = _parse_capture_time(entry.get("date_taken_utc"))
        dt_local = _parse_capture_time(entry.get("date_taken"))
        chosen_dt = dt_utc or dt_local

        geo_key, geo_entry = _get_geocode_entry(entry, geocode_cache, geocode_by_photo)

        gps = entry.get("gps") if isinstance(entry.get("gps"), dict) else {}
        location = entry.get("location") if isinstance(entry.get("location"), dict) else {}
        high_level_summary = {
            "location1": str(geo_entry.get("LLM_Watermark_Line1") or ""),
            "location2": str(geo_entry.get("LLM_Watermark_Line2") or ""),
        }

        raw_poi_search = geo_entry.get("poi_search") if isinstance(geo_entry.get("poi_search"), dict) else {}

        items.append(
            {
                "file_name": str(entry.get("file_name") or Path(source_key).name),
                "file_path": source_key,
                "album_name": album_name,
                "captured_at_utc": _normalized_dt_text(dt_utc),
                "captured_at_local": _normalized_dt_text(dt_local),
                "gps": {
                    "lat": gps.get("lat"),
                    "lon": gps.get("lon"),
                    "altitude": gps.get("altitude"),
                    "heading": gps.get("heading"),
                    "cardinal": gps.get("cardinal"),
                    "heading_ref": gps.get("heading_ref"),
                },
                "location": {
                    "formatted": location.get("formatted"),
                    "road": location.get("road"),
                    "city": location.get("city"),
                    "state": location.get("state"),
                    "country": location.get("country"),
                    "country_code": location.get("country_code"),
                    "display_name": location.get("display_name"),
                    "provider": location.get("provider"),
                },
                "high_level_summary": high_level_summary,
                "geocode_cache": {
                    "cache_key": geo_key,
                    "photos": geo_entry.get("photos") if isinstance(geo_entry.get("photos"), list) else [],
                    "nearby_pois": _compact_nearby_pois(geo_entry.get("nearby_pois")),
                    "poi_search": _compact_poi_search(raw_poi_search),
                },
                "_sort_dt": _normalized_dt_text(chosen_dt),
                "_tz_offset": _infer_offset_from_capture_pair(dt_utc, dt_local),
            }
        )

    items.sort(key=lambda it: (it.get("_sort_dt") is None, it.get("_sort_dt") or "", it.get("file_name") or ""))
    for idx, item in enumerate(items, start=1):
        item["sequence"] = idx
        item.pop("_sort_dt", None)

    captured_values = [i.get("captured_at_utc") or i.get("captured_at_local") for i in items]
    captured_values = [v for v in captured_values if isinstance(v, str) and v]

    captured_utc_values = [i.get("captured_at_utc") for i in items]
    captured_utc_values = [v for v in captured_utc_values if isinstance(v, str) and v]

    captured_local_values = [i.get("captured_at_local") for i in items]
    captured_local_values = [v for v in captured_local_values if isinstance(v, str) and v]

    tz_offsets = [i.get("_tz_offset") for i in items]
    tz_offsets = [v for v in tz_offsets if isinstance(v, str) and v]
    unique_offsets = sorted(set(tz_offsets))
    primary_offset = None
    if tz_offsets:
        primary_offset = max(set(tz_offsets), key=tz_offsets.count)

    for item in items:
        item.pop("_tz_offset", None)

    start_capture = captured_values[0] if captured_values else None
    end_capture = captured_values[-1] if captured_values else None

    output_album = album_filter or "all_albums"
    output_dir = pipeline_base / "travellog" / output_album
    output_path = output_dir / resolved_output_name
    legacy_rag_path = output_dir / f"{resolved_album}-rag.json"

    payload: Dict[str, Any] = {
        "travel_log_rag": {
            "generated_at": _utc_now_iso(),
            "album_filter": album_filter,
            "summary": {
                "photo_count": len(items),
                "start_capture": start_capture,
                "end_capture": end_capture,
                "start_capture_utc": captured_utc_values[0] if captured_utc_values else None,
                "end_capture_utc": captured_utc_values[-1] if captured_utc_values else None,
                "start_capture_local": captured_local_values[0] if captured_local_values else None,
                "end_capture_local": captured_local_values[-1] if captured_local_values else None,
                "timezone_offset": primary_offset,
                "timezone_offsets_observed": unique_offsets,
            },
            "source_files": {
                "master_json": str(master_path),
                "geocode_cache_json": str(geocode_path),
            },
            "entries": items,
        }
    }

    _save_json(output_path, payload)
    if legacy_rag_path.exists() and legacy_rag_path != output_path:
        legacy_rag_path.unlink()
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate chronological travel-log RAG JSON from master/geocode metadata",
    )
    parser.add_argument("--config", default="config/pipeline_config.json", help="Path to pipeline config")
    parser.add_argument("--album", default="", help="Optional album folder name filter")
    parser.add_argument("--output-name", default=None, help="Output JSON filename (default: {album}-LLMRAG-data.json)")
    parser.add_argument("--llm", "-llm", action="store_true", help="Generate Markdown travel story via Ollama from RAG")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    album_value = args.album.strip() if args.album else None

    out_path = generate_travel_log_from_config(config_path=args.config, album=album_value, output_name=args.output_name)
    print(f"✅ Travel log RAG JSON created: {out_path}")

    if args.llm:
        cfg = resolve_config_placeholders(_load_json(Path(args.config)))
        rag_payload = _load_json(out_path)
        output_album = album_value or "all_albums"
        try:
            story_path = generate_travel_story_markdown(
                config=cfg,
                rag_payload=rag_payload,
                output_dir=out_path.parent,
                output_album=output_album,
            )
            print(f"✅ Travel story Markdown created: {story_path}")
        except Exception as exc:
            print(f"❌ Failed to generate travel story Markdown via Ollama: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
