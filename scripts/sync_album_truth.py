#!/usr/bin/env python3
"""
Sync metadata and derivative paths to make pipeline/albums the source of truth.

What it does:
- Scans albums folder (paths.raw_input) for current source images.
- Re-keys moved source entries in master.json when the same filename exists in a new album folder.
- Updates nested paths in master.json for scaled, lora_processed, and watermarked_final outputs.
- Optionally moves existing derivative files on disk to the remapped album folder.
- Optionally reconciles geocode_cache.json photos[] lists against current album filenames.

Safety:
- Dry-run by default.
- Creates timestamped backups before writing when --apply is used.
- Never deletes lora_processed files.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

# Allow running this script directly from scripts/ while importing project modules.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.geo_extractor import GeoExtractor
from utils.config_utils import resolve_config_placeholders


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


@dataclass
class SyncStats:
    source_entries: int = 0
    unchanged_sources: int = 0
    moved_sources: int = 0
    ambiguous_sources: int = 0
    missing_sources_removed: int = 0
    key_collisions_merged: int = 0
    duplicate_filename_groups: int = 0
    unchanged_with_alt_locations: int = 0
    fingerprint_resolved_moves: int = 0
    manual_resolved_moves: int = 0

    path_updates: int = 0
    files_moved: int = 0
    file_move_conflicts: int = 0
    file_move_missing: int = 0

    geocode_entries_scanned: int = 0
    geocode_photo_refs_removed: int = 0


@dataclass
class SyncPlan:
    stats: SyncStats
    warnings: List[str]
    backups: List[Path]


@dataclass
class AlbumImageRecord:
    path: Path
    name: str
    size: Optional[int]
    timestamp: Optional[str]
    lat: Optional[float]
    lon: Optional[float]


def utc_now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "geocode_cache.json" and isinstance(data, dict):
        data = GeoExtractor(
            config={"metadata_extraction": {"providers": {"geocoding": {"cache": {"enabled": False}}}}}
        )._compact_cache_schema(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def backup_file(path: Path) -> Path:
    stamp = utc_now_stamp()
    backup_path = path.with_name(f"{path.name}.backup_{stamp}")
    shutil.copy2(path, backup_path)
    return backup_path


def load_manual_resolution_csv(csv_path: Path) -> Dict[str, str]:
    """Load user-supplied old->new source path overrides."""
    mapping: Dict[str, str] = {}
    if not csv_path.exists():
        return mapping

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            old_key = (row.get("old_source_path") or "").strip()
            new_key = (row.get("resolved_new_source_path") or "").strip()
            if old_key and new_key:
                mapping[old_key] = new_key
    return mapping


def _normalize_timestamp(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    # EXIF DateTimeOriginal format
    if len(v) >= 19 and v[4] == ':' and v[7] == ':':
        return f"{v[0:4]}-{v[5:7]}-{v[8:10]}T{v[11:19]}"
    # ISO-like format
    try:
        return datetime.fromisoformat(v.replace('Z', '+00:00')).strftime('%Y-%m-%dT%H:%M:%S')
    except Exception:
        return None


def _convert_to_degrees(value: Any) -> Optional[float]:
    try:
        d, m, s = value
        return float(d) + float(m) / 60.0 + float(s) / 3600.0
    except Exception:
        return None


def _extract_file_fingerprint(path: Path) -> AlbumImageRecord:
    size: Optional[int] = None
    timestamp: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    try:
        size = path.stat().st_size
    except Exception:
        size = None

    try:
        with Image.open(path) as img:
            exif = img._getexif() or {}
            exif_map: Dict[str, Any] = {}
            gps_map: Dict[str, Any] = {}

            for tag, val in exif.items():
                decoded = TAGS.get(tag, tag)
                exif_map[str(decoded)] = val
                if decoded == 'GPSInfo' and isinstance(val, dict):
                    for gps_tag, gps_val in val.items():
                        gps_decoded = GPSTAGS.get(gps_tag, gps_tag)
                        gps_map[str(gps_decoded)] = gps_val

            timestamp = _normalize_timestamp(
                exif_map.get('DateTimeOriginal') or exif_map.get('DateTime')
            )

            lat_raw = gps_map.get('GPSLatitude')
            lat_ref = gps_map.get('GPSLatitudeRef')
            lon_raw = gps_map.get('GPSLongitude')
            lon_ref = gps_map.get('GPSLongitudeRef')

            lat_v = _convert_to_degrees(lat_raw) if lat_raw is not None else None
            lon_v = _convert_to_degrees(lon_raw) if lon_raw is not None else None
            if lat_v is not None and lon_v is not None:
                if str(lat_ref).upper() not in {'N', "NORTH"}:
                    lat_v = -lat_v
                if str(lon_ref).upper() not in {'E', "EAST"}:
                    lon_v = -lon_v
                lat = round(lat_v, 6)
                lon = round(lon_v, 6)
    except Exception:
        # Best-effort: missing EXIF/unsupported format should not stop sync.
        pass

    return AlbumImageRecord(
        path=path,
        name=path.name,
        size=size,
        timestamp=timestamp,
        lat=lat,
        lon=lon,
    )


def _entry_fingerprint(entry: Dict[str, Any], fallback_name: str) -> Dict[str, Any]:
    date_taken = _normalize_timestamp(entry.get('date_taken_utc') or entry.get('date_taken'))

    gps = entry.get('gps') if isinstance(entry.get('gps'), dict) else {}
    location = entry.get('location') if isinstance(entry.get('location'), dict) else {}
    lat = gps.get('lat') if gps.get('lat') is not None else location.get('lat')
    lon = gps.get('lon') if gps.get('lon') is not None else location.get('lon')

    try:
        lat = round(float(lat), 6) if lat is not None else None
    except Exception:
        lat = None
    try:
        lon = round(float(lon), 6) if lon is not None else None
    except Exception:
        lon = None

    size = None
    prep = entry.get('preprocessing') if isinstance(entry.get('preprocessing'), dict) else {}
    for key in ('original_file_size', 'file_size', 'size'):
        if prep.get(key) is not None:
            size = prep.get(key)
            break
    if size is None and isinstance(entry.get('exif'), dict):
        size = entry['exif'].get('file_size')
    try:
        size = int(size) if size is not None else None
    except Exception:
        size = None

    return {
        'name': (entry.get('file_name') or fallback_name),
        'timestamp': date_taken,
        'lat': lat,
        'lon': lon,
        'size': size,
    }


def list_album_images(raw_root: Path) -> Tuple[Set[Path], Dict[str, List[Path]], Dict[str, AlbumImageRecord]]:
    paths: Set[Path] = set()
    by_name: Dict[str, List[Path]] = defaultdict(list)
    records_by_path: Dict[str, AlbumImageRecord] = {}

    for p in raw_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        ap = p.resolve()
        paths.add(ap)
        by_name[ap.name].append(ap)
        records_by_path[str(ap)] = _extract_file_fingerprint(ap)

    return paths, by_name, records_by_path


def _pick_best_candidate(
    entry: Dict[str, Any],
    old_path: Path,
    candidates: List[Path],
    records_by_path: Dict[str, AlbumImageRecord],
) -> Tuple[Optional[Path], bool]:
    """Return (candidate, resolved_by_fingerprint)."""
    fp = _entry_fingerprint(entry, old_path.name)
    cands = [records_by_path.get(str(c.resolve())) for c in candidates]
    cands = [c for c in cands if c is not None]

    def filt(pred):
        out = [c for c in cands if pred(c)]
        return out[0] if len(out) == 1 else None

    # Strong match: name + timestamp + gps
    if fp['timestamp'] is not None and fp['lat'] is not None and fp['lon'] is not None:
        m = filt(
            lambda c: c.name == fp['name']
            and c.timestamp == fp['timestamp']
            and c.lat == fp['lat']
            and c.lon == fp['lon']
        )
        if m:
            return m.path, True

    # Medium: name + timestamp + size
    if fp['timestamp'] is not None and fp['size'] is not None:
        m = filt(
            lambda c: c.name == fp['name']
            and c.timestamp == fp['timestamp']
            and c.size == fp['size']
        )
        if m:
            return m.path, True

    # Medium: name + gps + size
    if fp['lat'] is not None and fp['lon'] is not None and fp['size'] is not None:
        m = filt(
            lambda c: c.name == fp['name']
            and c.lat == fp['lat']
            and c.lon == fp['lon']
            and c.size == fp['size']
        )
        if m:
            return m.path, True

    return None, False


def _is_close_fingerprint_match(entry_fp: Dict[str, Any], candidate: AlbumImageRecord) -> bool:
    """Return True when candidate likely represents the same photo content."""
    matched = 0

    if entry_fp.get('timestamp') and candidate.timestamp:
        if entry_fp['timestamp'] == candidate.timestamp:
            matched += 1

    if (
        entry_fp.get('lat') is not None
        and entry_fp.get('lon') is not None
        and candidate.lat is not None
        and candidate.lon is not None
    ):
        if entry_fp['lat'] == candidate.lat and entry_fp['lon'] == candidate.lon:
            matched += 1

    if entry_fp.get('size') is not None and candidate.size is not None:
        if int(entry_fp['size']) == int(candidate.size):
            matched += 1

    # Require at least two matching attributes to avoid noisy basename-only warnings.
    return matched >= 2


def write_ambiguity_report_csv(
    out_path: Path,
    rows: List[Dict[str, Any]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "old_source_path",
        "file_name",
        "candidate_path",
        "candidate_size",
        "candidate_timestamp",
        "candidate_lat",
        "candidate_lon",
        "master_date_taken",
        "master_lat",
        "master_lon",
        "master_size",
        "resolved_new_source_path",
        "note",
    ]

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})


def _parts_tuple(path: Path) -> Tuple[str, ...]:
    return tuple(path.parts)


def remap_under_root(path_str: str, root: Path, old_rel_dir: Path, new_rel_dir: Path) -> str:
    """Replace album-relative directory segment under a root path."""
    if not path_str:
        return path_str

    p = Path(path_str)
    try:
        rel = p.resolve().relative_to(root.resolve())
    except Exception:
        return path_str

    rel_parts = _parts_tuple(rel)
    old_parts = _parts_tuple(old_rel_dir)
    new_parts = _parts_tuple(new_rel_dir)

    if len(old_parts) > len(rel_parts):
        return path_str
    if rel_parts[: len(old_parts)] != old_parts:
        return path_str

    remapped = root.joinpath(*new_parts, *rel_parts[len(old_parts) :])
    return str(remapped)


def queue_move_if_changed(
    moves: Set[Tuple[str, str]],
    old_path: str,
    new_path: str,
) -> bool:
    if not old_path or not new_path or old_path == new_path:
        return False
    moves.add((old_path, new_path))
    return True


def merge_entries(existing: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    """Conservative merge to keep generated outputs when key collisions occur."""
    # Keep destination as source of truth for direct scalar fields.
    for section in ("derivatives", "watermarked_outputs", "lora_outputs"):
        src = incoming.get(section)
        if isinstance(src, dict):
            dst = existing.setdefault(section, {})
            if isinstance(dst, dict):
                for k, v in src.items():
                    dst.setdefault(k, v)

    # Do not merge legacy lora_generations.<style> flat keys.
    # Consolidated style metadata lives under watermarked_outputs.<style>.

    # Keep watermark if missing on existing
    if "watermark" not in existing and "watermark" in incoming:
        existing["watermark"] = incoming["watermark"]

    # Merge pipeline stage list/timestamps
    p_existing = existing.setdefault("pipeline", {})
    p_incoming = incoming.get("pipeline") or {}

    stages_existing = set((p_existing.get("stages") or []))
    stages_incoming = set((p_incoming.get("stages") or []))
    if stages_incoming:
        p_existing["stages"] = sorted(stages_existing | stages_incoming)

    ts_existing = p_existing.setdefault("timestamps", {})
    ts_incoming = p_incoming.get("timestamps") or {}
    for stage, ts in ts_incoming.items():
        ts_existing.setdefault(stage, ts)


def rewrite_entry_paths(
    entry: Dict[str, Any],
    old_src: Path,
    new_src: Path,
    scaled_root: Path,
    lora_root: Path,
    watermarked_root: Path,
    moves: Set[Tuple[str, str]],
    stats: SyncStats,
) -> None:
    old_rel_dir = old_src.parent
    new_rel_dir = new_src.parent

    # derivatives.preprocessed.path
    derivatives = entry.get("derivatives")
    if isinstance(derivatives, dict):
        pre = derivatives.get("preprocessed")
        if isinstance(pre, dict) and isinstance(pre.get("path"), str):
            old_p = pre["path"]
            new_p = remap_under_root(old_p, scaled_root, old_rel_dir, new_rel_dir)
            if new_p != old_p:
                pre["path"] = new_p
                stats.path_updates += 1
                queue_move_if_changed(moves, old_p, new_p)

    # preprocessing section
    prep = entry.get("preprocessing")
    if isinstance(prep, dict):
        if isinstance(prep.get("output_path"), str):
            old_p = prep["output_path"]
            new_p = remap_under_root(old_p, scaled_root, old_rel_dir, new_rel_dir)
            if new_p != old_p:
                prep["output_path"] = new_p
                stats.path_updates += 1
                queue_move_if_changed(moves, old_p, new_p)
        if isinstance(prep.get("input_path"), str) and prep["input_path"] != str(new_src):
            prep["input_path"] = str(new_src)
            stats.path_updates += 1

    # lora_generations.<style>
    for key, value in list(entry.items()):
        if not key.startswith("lora_generations."):
            continue
        if not isinstance(value, dict):
            continue

        if isinstance(value.get("source_image"), str):
            old_p = value["source_image"]
            new_p = remap_under_root(old_p, scaled_root, old_rel_dir, new_rel_dir)
            if new_p != old_p:
                value["source_image"] = new_p
                stats.path_updates += 1

        if isinstance(value.get("output_path"), str):
            old_p = value["output_path"]
            new_p = remap_under_root(old_p, lora_root, old_rel_dir, new_rel_dir)
            if new_p != old_p:
                value["output_path"] = new_p
                stats.path_updates += 1
                queue_move_if_changed(moves, old_p, new_p)

    # watermarked_outputs.*
    wm_out = entry.get("watermarked_outputs")
    if isinstance(wm_out, dict):
        for _, style_entry in wm_out.items():
            if not isinstance(style_entry, dict):
                continue

            if isinstance(style_entry.get("lora_path"), str):
                old_p = style_entry["lora_path"]
                new_p = remap_under_root(old_p, lora_root, old_rel_dir, new_rel_dir)
                if new_p != old_p:
                    style_entry["lora_path"] = new_p
                    stats.path_updates += 1
                    queue_move_if_changed(moves, old_p, new_p)

            if isinstance(style_entry.get("output_path"), str):
                old_p = style_entry["output_path"]
                new_p = remap_under_root(old_p, watermarked_root, old_rel_dir, new_rel_dir)
                if new_p != old_p:
                    style_entry["output_path"] = new_p
                    stats.path_updates += 1
                    queue_move_if_changed(moves, old_p, new_p)

    # lora_outputs.* (if present)
    lora_out = entry.get("lora_outputs")
    if isinstance(lora_out, dict):
        for _, style_entry in lora_out.items():
            if not isinstance(style_entry, dict):
                continue
            if isinstance(style_entry.get("path"), str):
                old_p = style_entry["path"]
                new_p = remap_under_root(old_p, lora_root, old_rel_dir, new_rel_dir)
                if new_p != old_p:
                    style_entry["path"] = new_p
                    stats.path_updates += 1
                    queue_move_if_changed(moves, old_p, new_p)


def execute_moves(moves: Iterable[Tuple[str, str]], stats: SyncStats) -> None:
    for old_s, new_s in sorted(set(moves)):
        old_p = Path(old_s)
        new_p = Path(new_s)

        if not old_p.exists():
            stats.file_move_missing += 1
            continue

        if new_p.exists() and new_p.resolve() != old_p.resolve():
            stats.file_move_conflicts += 1
            continue

        new_p.parent.mkdir(parents=True, exist_ok=True)
        if old_p.resolve() != new_p.resolve():
            shutil.move(str(old_p), str(new_p))
            stats.files_moved += 1


def sync_master(
    master_data: Dict[str, Any],
    raw_root: Path,
    scaled_root: Path,
    lora_root: Path,
    watermarked_root: Path,
    album_paths: Set[Path],
    album_by_name: Dict[str, List[Path]],
    records_by_path: Dict[str, AlbumImageRecord],
    manual_resolutions: Dict[str, str],
    remove_missing_sources: bool,
) -> Tuple[Dict[str, Any], SyncStats, List[str], Set[Tuple[str, str]], List[Dict[str, Any]]]:
    stats = SyncStats()
    warnings: List[str] = []
    move_ops: Set[Tuple[str, str]] = set()
    ambiguity_rows: List[Dict[str, Any]] = []

    source_keys = [
        k
        for k in list(master_data.keys())
        if str(k).startswith(str(raw_root) + "/")
    ]

    stats.duplicate_filename_groups = sum(
        1 for paths in album_by_name.values() if len(paths) > 1
    )

    for old_key in source_keys:
        stats.source_entries += 1
        old_path = Path(old_key)
        old_abs = old_path.resolve()

        if old_abs in album_paths:
            entry = master_data[old_key]
            album_name = old_abs.parent.name
            if entry.get("album_name") != album_name:
                entry["album_name"] = album_name
                stats.path_updates += 1

            same_name_paths = album_by_name.get(old_path.name, [])
            if len(same_name_paths) > 1:
                fp = _entry_fingerprint(entry, old_path.name)
                close_alt_paths: List[str] = []
                for alt in same_name_paths:
                    if alt == old_abs:
                        continue
                    rec = records_by_path.get(str(alt))
                    if rec and _is_close_fingerprint_match(fp, rec):
                        close_alt_paths.append(str(alt))

                if close_alt_paths:
                    stats.unchanged_with_alt_locations += 1
                    warnings.append(
                        f"Unchanged but close duplicate fingerprint present: {old_key} | alternates: {close_alt_paths[:3]}"
                    )

            stats.unchanged_sources += 1
            continue

        candidates = album_by_name.get(old_path.name, [])
        chosen: Optional[Path] = None
        resolved_by_fp = False
        resolved_by_manual = False

        manual_new = manual_resolutions.get(old_key)
        if manual_new:
            manual_path = Path(manual_new).resolve()
            if manual_path in album_paths:
                chosen = manual_path
                resolved_by_manual = True
            else:
                warnings.append(
                    f"Manual resolution target not in albums for {old_key}: {manual_new}"
                )
        if chosen is None and len(candidates) == 1:
            chosen = candidates[0]
        elif chosen is None and len(candidates) > 1:
            chosen, resolved_by_fp = _pick_best_candidate(
                entry=master_data.get(old_key, {}),
                old_path=old_path,
                candidates=candidates,
                records_by_path=records_by_path,
            )

        if chosen is not None:
            new_abs = chosen
            new_key = str(new_abs)
            entry = master_data.pop(old_key)

            rewrite_entry_paths(
                entry=entry,
                old_src=old_abs,
                new_src=new_abs,
                scaled_root=scaled_root,
                lora_root=lora_root,
                watermarked_root=watermarked_root,
                moves=move_ops,
                stats=stats,
            )

            entry["file_path"] = new_key
            entry["file_name"] = new_abs.name
            entry["album_name"] = new_abs.parent.name
            stats.path_updates += 3

            if new_key in master_data:
                merge_entries(master_data[new_key], entry)
                stats.key_collisions_merged += 1
                warnings.append(
                    f"Merged collision for moved source {old_key} -> {new_key}"
                )
            else:
                master_data[new_key] = entry

            stats.moved_sources += 1
            if resolved_by_fp:
                stats.fingerprint_resolved_moves += 1
            if resolved_by_manual:
                stats.manual_resolved_moves += 1
            continue

        if len(candidates) > 1:
            stats.ambiguous_sources += 1
            fp = _entry_fingerprint(master_data.get(old_key, {}), old_path.name)
            for cand in candidates:
                rec = records_by_path.get(str(cand.resolve()))
                ambiguity_rows.append(
                    {
                        "old_source_path": old_key,
                        "file_name": old_path.name,
                        "candidate_path": str(cand.resolve()),
                        "candidate_size": rec.size if rec else "",
                        "candidate_timestamp": rec.timestamp if rec else "",
                        "candidate_lat": rec.lat if rec else "",
                        "candidate_lon": rec.lon if rec else "",
                        "master_date_taken": fp.get("timestamp") or "",
                        "master_lat": fp.get("lat") if fp.get("lat") is not None else "",
                        "master_lon": fp.get("lon") if fp.get("lon") is not None else "",
                        "master_size": fp.get("size") if fp.get("size") is not None else "",
                        "resolved_new_source_path": "",
                        "note": "fill resolved_new_source_path and rerun with --manual-resolve-csv",
                    }
                )
            warnings.append(
                f"Ambiguous move for {old_key}: {len(candidates)} album files share name {old_path.name}"
            )
            continue

        # No candidates in albums source-of-truth
        if remove_missing_sources:
            master_data.pop(old_key, None)
            stats.missing_sources_removed += 1
        else:
            warnings.append(f"Missing source kept: {old_key}")

    return master_data, stats, warnings, move_ops, ambiguity_rows


def reconcile_geocode_cache(
    geocode_data: Dict[str, Any],
    current_filenames: Set[str],
    stats: SyncStats,
) -> Dict[str, Any]:
    for _, geo_entry in geocode_data.items():
        if not isinstance(geo_entry, dict):
            continue
        photos = geo_entry.get("photos")
        if not isinstance(photos, list):
            continue

        stats.geocode_entries_scanned += 1
        filtered = [p for p in photos if isinstance(p, str) and p in current_filenames]
        removed = len(photos) - len(filtered)
        if removed > 0:
            geo_entry["photos"] = filtered
            stats.geocode_photo_refs_removed += removed

    return geocode_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync master.json (and optional geocode_cache.json) to albums as source-of-truth",
    )
    parser.add_argument("--config", default="config/pipeline_config.json", help="Path to pipeline config")
    parser.add_argument("--apply", action="store_true", help="Write changes and move files (dry-run by default)")
    parser.add_argument(
        "--no-move-files",
        action="store_true",
        help="Do not move scaled/lora_processed/watermarked files on disk (metadata only)",
    )
    parser.add_argument(
        "--keep-missing-sources",
        action="store_true",
        help="Keep master entries that have no matching source file in albums",
    )
    parser.add_argument(
        "--skip-geocode-sync",
        action="store_true",
        help="Do not reconcile geocode_cache.json photos[]",
    )
    parser.add_argument(
        "--manual-resolve-csv",
        default="",
        help="CSV with old_source_path,resolved_new_source_path to force ambiguous move mapping",
    )
    parser.add_argument(
        "--ambiguity-report-csv",
        default="",
        help="Where to write unresolved ambiguity report CSV (default: metadata_dir/sync_album_truth_ambiguities.csv)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    cfg_path = Path(args.config)
    config = resolve_config_placeholders(load_json(cfg_path))
    paths = config.get("paths", {})

    raw_root = Path(paths.get("raw_input", "")).resolve()
    scaled_root = Path(paths.get("preprocessed", "")).resolve()
    lora_root = Path(paths.get("lora_processed", "")).resolve()
    watermarked_root = Path(paths.get("watermarked_final", "")).resolve()
    master_path = Path(paths.get("master_catalog", "")).resolve()
    geocode_path = Path(paths.get("metadata_dir", "")).resolve() / "geocode_cache.json"
    default_report_csv = Path(paths.get("metadata_dir", "")).resolve() / "sync_album_truth_ambiguities.csv"
    report_csv = Path(args.ambiguity_report_csv).resolve() if args.ambiguity_report_csv else default_report_csv

    if not raw_root.exists():
        print(f"ERROR: albums source folder not found: {raw_root}")
        return 2
    if not master_path.exists():
        print(f"ERROR: master.json not found: {master_path}")
        return 2

    print("=" * 80)
    print("ALBUM SOURCE-OF-TRUTH SYNC")
    print("=" * 80)
    print(f"Albums source:      {raw_root}")
    print(f"Master file:        {master_path}")
    print(f"Scaled root:        {scaled_root}")
    print(f"LoRA root:          {lora_root}")
    print(f"Watermarked root:   {watermarked_root}")
    print(f"Mode:               {'APPLY' if args.apply else 'DRY-RUN'}")

    album_paths, album_by_name, records_by_path = list_album_images(raw_root)
    current_filenames = {p.name for p in album_paths}
    print(f"Album images found: {len(album_paths)}")

    manual_resolutions: Dict[str, str] = {}
    if args.manual_resolve_csv:
        manual_resolutions = load_manual_resolution_csv(Path(args.manual_resolve_csv).resolve())
        print(f"Manual resolutions loaded: {len(manual_resolutions)}")

    master_data = load_json(master_path)

    master_data, stats, warnings, move_ops, ambiguity_rows = sync_master(
        master_data=master_data,
        raw_root=raw_root,
        scaled_root=scaled_root,
        lora_root=lora_root,
        watermarked_root=watermarked_root,
        album_paths=album_paths,
        album_by_name=album_by_name,
        records_by_path=records_by_path,
        manual_resolutions=manual_resolutions,
        remove_missing_sources=not args.keep_missing_sources,
    )

    geocode_data: Optional[Dict[str, Any]] = None
    if not args.skip_geocode_sync and geocode_path.exists():
        geocode_data = load_json(geocode_path)
        geocode_data = reconcile_geocode_cache(geocode_data, current_filenames, stats)

    print("\nPlanned changes")
    print("-" * 80)
    print(f"Source entries scanned:            {stats.source_entries}")
    print(f"Source entries unchanged:          {stats.unchanged_sources}")
    print(f"Duplicate filename groups:         {stats.duplicate_filename_groups}")
    print(f"Unchanged w/ alternate locations:  {stats.unchanged_with_alt_locations}")
    print(f"Source entries moved/rekeyed:      {stats.moved_sources}")
    print(f"Moved resolved by fingerprint:     {stats.fingerprint_resolved_moves}")
    print(f"Moved resolved by manual CSV:      {stats.manual_resolved_moves}")
    print(f"Source entries ambiguous:          {stats.ambiguous_sources}")
    print(f"Missing source entries removed:    {stats.missing_sources_removed}")
    print(f"Master key collisions merged:      {stats.key_collisions_merged}")
    print(f"Metadata path fields updated:      {stats.path_updates}")
    print(f"Derivative file moves queued:      {len(move_ops)}")
    print(f"Geocode entries scanned:           {stats.geocode_entries_scanned}")
    print(f"Geocode photo refs removed:        {stats.geocode_photo_refs_removed}")

    write_ambiguity_report_csv(report_csv, ambiguity_rows)
    print(f"Ambiguity report CSV:              {report_csv}")
    print(f"Ambiguity report rows:             {len(ambiguity_rows)}")

    if warnings:
        print("\nWarnings")
        print("-" * 80)
        for w in warnings[:30]:
            print(f"- {w}")
        if len(warnings) > 30:
            print(f"- ... {len(warnings) - 30} more")

    if not args.apply:
        print("\nDry-run complete. Re-run with --apply to persist changes.")
        if ambiguity_rows:
            print("Resolve ambiguous rows by filling resolved_new_source_path, then rerun with --manual-resolve-csv.")
        else:
            print("No ambiguous source matches found; report file contains header only.")
        return 0

    backups: List[Path] = []
    backups.append(backup_file(master_path))
    if geocode_data is not None:
        backups.append(backup_file(geocode_path))

    if not args.no_move_files:
        execute_moves(move_ops, stats)

    save_json(master_path, master_data)
    if geocode_data is not None:
        save_json(geocode_path, geocode_data)

    print("\nApplied")
    print("-" * 80)
    print(f"Backups created:                   {len(backups)}")
    for bp in backups:
        print(f"- {bp}")
    print(f"Derivative files moved:            {stats.files_moved}")
    print(f"Derivative move conflicts:         {stats.file_move_conflicts}")
    print(f"Derivative move missing-sources:   {stats.file_move_missing}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
