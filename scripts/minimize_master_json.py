#!/usr/bin/env python3
"""Audit and minimize pipeline master.json to the strict runtime schema.

This tool keeps only source-image entries (under pipeline/albums by default)
and trims each entry to fields needed by runtime pipeline stages.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from core.master_store import MasterStore
from utils.config_utils import resolve_config_placeholders


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "pipeline_config.json"


def load_default_paths(config_path: Path) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = resolve_config_placeholders(json.load(f))
    return (cfg or {}).get("paths", {}) or {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and minimize master.json")
    parser.add_argument(
        "--master",
        default="",
        help="Path to master.json (defaults to config paths.master_catalog)",
    )
    parser.add_argument(
        "--source-root",
        default="",
        help="Source image root to keep (defaults to config paths.raw_input)",
    )
    parser.add_argument(
        "--drop-missing",
        action="store_true",
        help="Drop entries whose source files no longer exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing master.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    paths = load_default_paths(DEFAULT_CONFIG)
    master_path = Path(args.master or paths.get("master_catalog", "")).expanduser()
    source_root = args.source_root or paths.get("raw_input", "")

    if not master_path:
        print("ERROR: master path is empty")
        return 1
    if not master_path.exists():
        print(f"ERROR: master.json not found: {master_path}")
        return 1

    store = MasterStore(str(master_path), auto_save=False)
    stats = store.prune_to_minimal(
        source_root=str(source_root) if source_root else None,
        drop_missing_files=bool(args.drop_missing),
    )

    print("MASTER MINIMIZATION AUDIT")
    print(f"  master: {master_path}")
    print(f"  source_root: {source_root or '(not set)'}")
    print(f"  entries_before: {stats.get('entries_before', 0)}")
    print(f"  entries_after: {stats.get('entries_after', 0)}")
    print(f"  removed_non_source: {stats.get('removed_non_source', 0)}")
    print(f"  removed_missing: {stats.get('removed_missing', 0)}")
    print(f"  pruned_entries: {stats.get('pruned_entries', 0)}")

    if args.dry_run:
        print("DRY RUN: no file written")
        return 0

    store.save()
    print("Saved minimized master.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
