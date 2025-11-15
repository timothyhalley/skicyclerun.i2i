#!/usr/bin/env python3
"""Master Catalog Builder

Creates a single authoritative master.json keyed by absolute file path.

Sources:
    1. catalog.json (existing per-image metadata keyed by file path)
    2. geocode_cache.json (reverse geocode entries keyed by coordinate string)

Merged structure (per file_path key):
{
    "<file_path>": {
            "file_name": str,
            "timestamp": str|None,
            "date_taken": str|None,
            "gps": {"lat": float, "lon": float} | None,
            "exif": {  # raw original EXIF-derived location block from catalog
                    "location": {... original location block ...}
            },
            "geocode_raw": {  # full raw entry from geocode_cache if available
                    "city": ..., "state": ..., "country": ..., "country_code": ..., "display_name": ..., "lat": ..., "lon": ...
            } | None,
            "location": {  # unified preferred location (geocode_raw overrides exif)
                    "city": ..., "state": ..., "country": ..., "country_code": ..., "display_name": ...
            },
            "location_formatted": str|None
    }
}

If geocode_raw present it overrides missing fields and is also preserved intact.
"""
from pathlib import Path
import json
from typing import Dict, Any

def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def normalize_geocode_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "city": entry.get("city"),
        "state": entry.get("state"),
        "country": entry.get("country"),
        "country_code": entry.get("country_code"),
        "display_name": entry.get("display_name"),
        "lat": entry.get("lat"),
        "lon": entry.get("lon"),
    }

def build_master(catalog: Dict[str, Any], geocode_cache: Dict[str, Any]) -> Dict[str, Any]:
    master: Dict[str, Any] = {}

    # Reverse index geocode cache by rounded coordinates
    geo_index: Dict[tuple, Dict[str, Any]] = {}
    for _, data in geocode_cache.items():
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is not None and lon is not None:
            geo_index[(round(lat, 6), round(lon, 6))] = normalize_geocode_entry(data)

    for file_path, meta in catalog.items():
        gps = meta.get("gps_coordinates", {})
        lat = gps.get("lat")
        lon = gps.get("lon")
        exif_location = meta.get("location", {}) or {}
        formatted = meta.get("location_formatted")

        geocode_raw = None
        if lat is not None and lon is not None:
            geocode_raw = geo_index.get((round(lat, 6), round(lon, 6)))

        # Build unified location block
        if geocode_raw:
            location_out = {
                "city": geocode_raw.get("city") or exif_location.get("city"),
                "state": geocode_raw.get("state") or exif_location.get("state"),
                "country": geocode_raw.get("country") or exif_location.get("country"),
                "country_code": geocode_raw.get("country_code") or exif_location.get("country_code"),
                "display_name": geocode_raw.get("display_name") or exif_location.get("display_name")
            }
        else:
            location_out = {
                "city": exif_location.get("city"),
                "state": exif_location.get("state"),
                "country": exif_location.get("country"),
                "country_code": exif_location.get("country_code"),
                "display_name": exif_location.get("display_name")
            }

        master[file_path] = {
            "file_name": meta.get("file_name"),
            "file_path": file_path,
            "timestamp": meta.get("timestamp"),
            "date_taken": meta.get("date_taken"),
            "gps": {"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
            "exif": {"location": exif_location} if exif_location else None,
            "geocode_raw": geocode_raw,
            "location": location_out,
            "location_formatted": formatted
        }

    return master

def save_json(path: Path, data: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def build_from_paths(catalog_path: Path, geocode_cache_path: Path, master_path: Path):
    catalog = load_json(catalog_path)
    geocode_cache = load_json(geocode_cache_path)
    master = build_master(catalog, geocode_cache)
    save_json(master_path, master)
    return master

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build unified master catalog")
    parser.add_argument("--catalog", required=True, help="Path to existing catalog.json")
    parser.add_argument("--geocode", required=True, help="Path to geocode_cache.json")
    parser.add_argument("--output", required=True, help="Path to master_catalog.json")
    args = parser.parse_args()

    catalog_path = Path(args.catalog)
    geocode_path = Path(args.geocode)
    out_path = Path(args.output)

    master = build_from_paths(catalog_path, geocode_path, out_path)
    print(f"✅ Master catalog written: {out_path} ({len(master)} entries)")
