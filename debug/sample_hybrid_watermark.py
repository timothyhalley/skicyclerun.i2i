#!/usr/bin/env python3
"""
Dry-run validation: simulate exactly what `run_Pipeline --stages post_lora_watermarking`
would produce for each geocode_cache entry that has LLM analysis lines.

Shows a three-way comparison per entry:
  CACHE LLM  — raw LLM_Watermark_Line1/2 stored in geocode_cache.json
  RULES ONLY — deterministic rule engine (LLM blend disabled)
  PIPELINE   — final output the watermarking stage would apply (hybrid + copyright)

Also surfaces any known_location_hints.json matches that would override lines.

Usage:
    python3 debug/sample_hybrid_watermark.py [--limit 20] [--album Kelowna]
    python3 debug/sample_hybrid_watermark.py --changed-only
    python3 debug/sample_hybrid_watermark.py --hint-only   # only show hint-matched entries
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CACHE_PATH = Path("/Volumes/MySSD/skicyclerun.i2i/pipeline/metadata/geocode_cache.json")

# ── separator widths ────────────────────────────────────────────────────────
W = 72


def _load_cache(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _rule_only_result(lat: float, lon: float, geo: dict) -> dict:
    """Call build_watermark_from_cached_context with LLM blend disabled."""
    from core.poi_watermark_engine import build_watermark_from_cached_context, LLM_BLEND_CONFIG

    orig = LLM_BLEND_CONFIG.get("enabled", True)
    LLM_BLEND_CONFIG["enabled"] = False
    try:
        return build_watermark_from_cached_context(lat, lon, cached_geo=geo)
    finally:
        LLM_BLEND_CONFIG["enabled"] = orig


def _pipeline_result(lat: float, lon: float, geo: dict) -> dict:
    """Exactly what run_post_lora_watermarking_stage calls per image."""
    from core.poi_watermark_engine import build_watermark_from_cached_context

    return build_watermark_from_cached_context(lat, lon, cached_geo=geo)


def _print_entry(coord: str, geo: dict, rule: dict, pipeline: dict) -> None:
    photos = geo.get("photos") or []
    photo_str = ", ".join(photos[:2]) + ("…" if len(photos) > 2 else "")

    llm1 = str(geo.get("LLM_Watermark_Line1") or "").strip()
    llm2 = str(geo.get("LLM_Watermark_Line2") or "").strip()

    r1, r2 = rule.get("line1", ""), rule.get("line2", "")
    p1, p2 = pipeline.get("line1", ""), pipeline.get("line2", "")
    src1, src2 = pipeline.get("line1_source", "rules"), pipeline.get("line2_source", "rules")

    known_hint = pipeline.get("known_hint")
    changed = (r1 != p1) or (r2 != p2)

    tag = ""
    if known_hint:
        tag = "  ◀ HINT OVERRIDE"
    elif changed:
        tag = "  ◀ CHANGED"

    print("─" * W)
    print(f"  coord  : {coord}{tag}")
    print(f"  photos : {photo_str}")
    if known_hint:
        print(f"  hint   : {known_hint.get('name')}  ({known_hint.get('distance_m', 0):.0f} m)")
    print()
    print(f"  CACHE LLM   L1 : {llm1 or '(none)'}")
    print(f"  CACHE LLM   L2 : {llm2 or '(none)'}")
    print()
    print(f"  RULES ONLY  L1 : {r1}")
    print(f"  RULES ONLY  L2 : {r2}")
    print()
    print(f"  PIPELINE    L1 : {p1}  [{src1}]")
    print(f"  PIPELINE    L2 : {p2}  [{src2}]")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Dry-run: simulate post_lora_watermarking for geocode_cache entries"
    )
    parser.add_argument("--limit", type=int, default=20, help="Max entries to show (default 20)")
    parser.add_argument("--album", type=str, default="", help="Filter by city/state/country substring")
    parser.add_argument("--changed-only", action="store_true", help="Only show entries where PIPELINE differs from RULES")
    parser.add_argument("--hint-only", action="store_true", help="Only show entries that match a known_location_hint")
    parser.add_argument("--cache", type=str, default=str(CACHE_PATH), help="Override geocode_cache.json path")
    args = parser.parse_args()

    cache_path = Path(args.cache)
    print(f"Loading geocode cache: {cache_path}")
    cache = _load_cache(cache_path)
    print(f"  {len(cache)} entries loaded.\n")

    shown = 0
    changed_count = 0
    hint_count = 0
    skipped_no_llm = 0

    for coord_key, geo in cache.items():
        if shown >= args.limit:
            break
        if not isinstance(geo, dict):
            continue

        # Location filter
        location_str = " ".join(
            str(geo.get(k) or "") for k in ("city", "state", "country")
        )
        if args.album and args.album.lower() not in location_str.lower():
            continue

        llm1 = str(geo.get("LLM_Watermark_Line1") or "").strip()
        llm2 = str(geo.get("LLM_Watermark_Line2") or "").strip()
        if not llm1 and not llm2:
            skipped_no_llm += 1
            continue

        try:
            lat, lon = (float(x) for x in coord_key.split(","))
        except ValueError:
            continue

        rule = _rule_only_result(lat, lon, geo)
        pipeline = _pipeline_result(lat, lon, geo)

        r1, r2 = rule.get("line1", ""), rule.get("line2", "")
        p1, p2 = pipeline.get("line1", ""), pipeline.get("line2", "")
        changed = (r1 != p1) or (r2 != p2)
        has_hint = bool(pipeline.get("known_hint"))

        if has_hint:
            hint_count += 1
        if changed:
            changed_count += 1

        if args.changed_only and not changed:
            continue
        if args.hint_only and not has_hint:
            continue

        _print_entry(coord_key, geo, rule, pipeline)
        shown += 1

    print("═" * W)
    print(f"  DRY RUN COMPLETE — no files written")
    print(f"  Shown   : {shown}")
    print(f"  Changed : {changed_count}  (PIPELINE differs from RULES ONLY)")
    print(f"  Hints   : {hint_count}  (known_location_hints.json match)")
    print(f"  Skipped : {skipped_no_llm}  (no LLM lines in cache)")
    print("═" * W)


if __name__ == "__main__":
    main()
