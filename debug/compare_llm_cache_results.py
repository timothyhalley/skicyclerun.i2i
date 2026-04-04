#!/usr/bin/env python3
"""Compare LLM watermark fields between two geocode_cache JSON files.

Usage:
  python debug/compare_llm_cache_results.py \
    --before /path/to/geocode_cache.before.json \
    --after  /path/to/geocode_cache.json

Optional flags:
  --only-changed       show only entries where line1/line2 changed
  --limit N            show at most N detailed rows
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


LINE1_KEY = "LLM_Watermark_Line1"
LINE2_KEY = "LLM_Watermark_Line2"


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected top-level JSON object in {path}")
    return data


def _get_lines(entry: Dict[str, Any]) -> Tuple[str, str]:
    line1 = str(entry.get(LINE1_KEY) or "").strip()
    line2 = str(entry.get(LINE2_KEY) or "").strip()
    return line1, line2


def _photo_hint(entry: Dict[str, Any]) -> str:
    photos = entry.get("photos") or []
    if isinstance(photos, list) and photos:
        return str(photos[0])
    return "(no-photo)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare LLM watermark lines in geocode cache snapshots")
    parser.add_argument("--before", required=True, help="Path to before snapshot JSON")
    parser.add_argument("--after", required=True, help="Path to after snapshot JSON")
    parser.add_argument("--only-changed", action="store_true", help="Show only entries where line1/line2 changed")
    parser.add_argument("--limit", type=int, default=50, help="Max detailed rows to print (default: 50)")
    args = parser.parse_args()

    before_path = Path(args.before).expanduser().resolve()
    after_path = Path(args.after).expanduser().resolve()

    before = _load_json(before_path)
    after = _load_json(after_path)

    all_keys = sorted(set(before.keys()) | set(after.keys()))

    changed = []
    unchanged = 0
    added_lines = 0
    removed_lines = 0

    for key in all_keys:
        b_entry = before.get(key, {}) or {}
        a_entry = after.get(key, {}) or {}

        b1, b2 = _get_lines(b_entry)
        a1, a2 = _get_lines(a_entry)

        b_has = bool(b1 or b2)
        a_has = bool(a1 or a2)

        if (b1, b2) == (a1, a2):
            unchanged += 1
            continue

        if not b_has and a_has:
            added_lines += 1
        elif b_has and not a_has:
            removed_lines += 1

        changed.append(
            {
                "key": key,
                "photo": _photo_hint(a_entry or b_entry),
                "before_line1": b1,
                "before_line2": b2,
                "after_line1": a1,
                "after_line2": a2,
            }
        )

    total = len(all_keys)
    print("=" * 80)
    print("LLM Watermark Compare")
    print("=" * 80)
    print(f"Before: {before_path}")
    print(f"After : {after_path}")
    print()
    print(f"Total entries         : {total}")
    print(f"Changed line entries  : {len(changed)}")
    print(f"Unchanged entries     : {unchanged}")
    print(f"Newly added lines     : {added_lines}")
    print(f"Removed lines         : {removed_lines}")

    rows = changed if args.only_changed else changed
    if not rows:
        print("\nNo differences found in LLM watermark fields.")
        return 0

    limit = max(0, int(args.limit))
    if limit:
        rows = rows[:limit]

    print("\nDetailed changes:")
    for idx, row in enumerate(rows, 1):
        print("-" * 80)
        print(f"{idx}. {row['photo']} @ {row['key']}")
        print(f"   BEFORE L1: {row['before_line1'] or '(empty)'}")
        print(f"   BEFORE L2: {row['before_line2'] or '(empty)'}")
        print(f"   AFTER  L1: {row['after_line1'] or '(empty)'}")
        print(f"   AFTER  L2: {row['after_line2'] or '(empty)'}")

    if len(changed) > len(rows):
        print("-" * 80)
        print(f"... {len(changed) - len(rows)} more changed entries not shown (increase --limit)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
