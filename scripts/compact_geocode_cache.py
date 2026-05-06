#!/usr/bin/env python3
"""Compact geocode_cache.json while preserving runtime-required fields.

This removes heavyweight metadata blobs and normalizes cache entries to a
stable minimal schema used by pipeline stages.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict

from core.geo_extractor import GeoExtractor
from utils.config_utils import resolve_config_placeholders


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "pipeline_config.json"


def load_paths(config_path: Path) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = resolve_config_placeholders(json.load(f))
    return (cfg or {}).get("paths", {}) or {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compact geocode_cache.json")
    parser.add_argument(
        "--cache",
        default="",
        help="Path to geocode_cache.json (defaults to config paths.metadata_dir/geocode_cache.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and report without writing file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    paths = load_paths(DEFAULT_CONFIG)
    default_cache = Path(paths.get("metadata_dir", "")) / "geocode_cache.json"
    cache_path = Path(args.cache or default_cache).expanduser()

    if not cache_path.exists():
        print(f"ERROR: geocode_cache.json not found: {cache_path}")
        return 1

    before_raw = json.loads(cache_path.read_text(encoding="utf-8"))
    before_bytes = cache_path.stat().st_size
    before_entries = len(before_raw) if isinstance(before_raw, dict) else 0

    extractor = GeoExtractor(config={"metadata_extraction": {"providers": {"geocoding": {"cache": {"enabled": False}}}}})
    compact = extractor._compact_cache_schema(before_raw if isinstance(before_raw, dict) else {})

    compact_text = json.dumps(compact, indent=2, ensure_ascii=False)
    after_bytes = len(compact_text.encode("utf-8"))
    after_entries = len(compact)

    print("GEOCODE CACHE COMPACTION")
    print(f"  cache: {cache_path}")
    print(f"  entries_before: {before_entries}")
    print(f"  entries_after: {after_entries}")
    print(f"  bytes_before: {before_bytes}")
    print(f"  bytes_after: {after_bytes}")
    print(f"  bytes_saved: {before_bytes - after_bytes}")

    if args.dry_run:
        print("DRY RUN: no file written")
        return 0

    backup = cache_path.with_name(
        f"geocode_cache.backup_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    )
    shutil.copy2(cache_path, backup)
    cache_path.write_text(compact_text + "\n", encoding="utf-8")

    print(f"  backup: {backup}")
    print("Saved compacted geocode_cache.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
