"""Master Store

Incremental read/update/write utility for the unified `master.json` metadata file.

Each entry is keyed by absolute file path. Updates merge shallow dict keys and
merge nested section dicts rather than overwriting whole entries unless explicitly
requested.

Usage:
    store = MasterStore(path_to_master_json)
    store.update_entry(file_path, {"exif": {...}, "gps": {...}})
    store.update_section(file_path, "preprocessing", {...})
    store.save()  # optional explicit save (auto-save by update_* by default)

The helper keeps everything in memory; given expected catalog sizes this is fine.
Write operations are atomic via temporary file + replace to reduce corruption risk.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from utils.time_utils import utc_now_iso_z


class MasterStore:
    _ALLOWED_TOP_LEVEL_KEYS = {
        "file_path",
        "file_name",
        "pipeline",
        "date_taken",
        "date_taken_utc",
        "gps",
        "location",
        "derivatives",
        "watermark_ref",
        "watermarked_outputs",
    }

    _ALLOWED_PIPELINE_KEYS = {"stages", "timestamps", "last_updated"}
    _ALLOWED_GPS_KEYS = {"lat", "lon", "altitude", "heading", "cardinal", "heading_ref"}
    _ALLOWED_LOCATION_KEYS = {
        "formatted",
        "city",
        "state",
        "country",
        "country_code",
        "road",
        "display_name",
    }
    _ALLOWED_DERIVATIVE_KEYS = {"path", "timestamp"}
    _ALLOWED_WATERMARK_REF_KEYS = {"cache_key", "updated_at"}
    _ALLOWED_WATERMARK_OUTPUT_KEYS = {
        "lora_path",
        "output_path",
        "applied_at",
        "output_name",
        "generated_at",
        "seed",
    }
    _ALLOWED_LORA_KEYS = {"style", "seed", "output_path", "output_name", "generated_at"}

    def __init__(self, master_path: str, auto_save: bool = True):
        self.master_path = Path(master_path)
        self.auto_save = auto_save
        self.data: Dict[str, Dict[str, Any]] = {}
        self._loaded = False
        self.load()

    # ---------- Core IO ----------
    def load(self) -> None:
        if self.master_path.exists():
            try:
                with open(self.master_path, 'r') as f:
                    self.data = json.load(f)
            except Exception:
                # Corrupted file fallback: keep empty and allow rebuild
                self.data = {}
        self._loaded = True

    def save(self) -> None:
        self.master_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.master_path.with_suffix('.tmp')
        with open(tmp_path, 'w') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(self.master_path)

    # ---------- Minimal Schema Helpers ----------
    def _compact_gps(self, gps: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(gps, dict):
            return None
        compact = {k: gps.get(k) for k in self._ALLOWED_GPS_KEYS if gps.get(k) is not None}
        if compact.get("lat") is None or compact.get("lon") is None:
            return None
        return compact

    def _compact_location(self, location: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(location, dict):
            return None
        compact = {k: location.get(k) for k in self._ALLOWED_LOCATION_KEYS if location.get(k) not in (None, "")}
        return compact or None

    def _compact_pipeline(self, pipeline: Any) -> Dict[str, Any]:
        if not isinstance(pipeline, dict):
            return {
                "stages": [],
                "timestamps": {},
                "last_updated": utc_now_iso_z(),
            }

        stages = pipeline.get("stages")
        if not isinstance(stages, list):
            stages = []
        timestamps = pipeline.get("timestamps")
        if not isinstance(timestamps, dict):
            timestamps = {}
        last_updated = pipeline.get("last_updated") or utc_now_iso_z()

        return {
            "stages": stages,
            "timestamps": timestamps,
            "last_updated": last_updated,
        }

    def _compact_derivatives(self, derivatives: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(derivatives, dict):
            return None

        compact: Dict[str, Dict[str, Any]] = {}
        preprocessed = derivatives.get("preprocessed")
        if isinstance(preprocessed, dict):
            reduced = {
                k: preprocessed.get(k)
                for k in self._ALLOWED_DERIVATIVE_KEYS
                if preprocessed.get(k) not in (None, "")
            }
            if reduced.get("path"):
                compact["preprocessed"] = reduced

        return compact or None

    def _compact_watermark_ref(self, watermark_ref: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(watermark_ref, dict):
            return None
        compact = {
            k: watermark_ref.get(k)
            for k in self._ALLOWED_WATERMARK_REF_KEYS
            if watermark_ref.get(k) not in (None, "")
        }
        if compact.get("cache_key"):
            return compact
        return None

    def _compact_watermarked_outputs(self, outputs: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(outputs, dict):
            return None
        compact: Dict[str, Dict[str, Any]] = {}
        for style, payload in outputs.items():
            if not isinstance(payload, dict):
                continue
            reduced = {
                k: payload.get(k)
                for k in self._ALLOWED_WATERMARK_OUTPUT_KEYS
                if payload.get(k) not in (None, "")
            }
            # Keep style rows if either LoRA output or watermarked output exists.
            if reduced.get("lora_path") or reduced.get("output_path"):
                compact[str(style)] = reduced
        return compact or None

    def _compact_lora_generation(self, payload: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        compact = {
            k: payload.get(k)
            for k in self._ALLOWED_LORA_KEYS
            if payload.get(k) not in (None, "")
        }
        if compact.get("output_path"):
            return compact
        return None

    def _merge_lora_generations_into_watermarked_outputs(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Consolidate legacy lora_generations.* rows into watermarked_outputs.<style>."""
        merged: Dict[str, Dict[str, Any]] = {}

        existing_outputs = entry.get("watermarked_outputs")
        if isinstance(existing_outputs, dict):
            for style, payload in existing_outputs.items():
                if not isinstance(payload, dict):
                    continue
                style_key = str(style)
                merged.setdefault(style_key, {})
                for key in self._ALLOWED_WATERMARK_OUTPUT_KEYS:
                    value = payload.get(key)
                    if value not in (None, ""):
                        merged[style_key][key] = value

        for key, value in entry.items():
            if not key.startswith("lora_generations."):
                continue
            style_key = key.split(".", 1)[1]
            compact_lora = self._compact_lora_generation(value)
            if not compact_lora:
                continue
            merged.setdefault(style_key, {})
            # Keep canonical LoRA output path under lora_path.
            if compact_lora.get("output_path") and not merged[style_key].get("lora_path"):
                merged[style_key]["lora_path"] = compact_lora.get("output_path")
            for lora_key in ("output_name", "generated_at", "seed"):
                lora_value = compact_lora.get(lora_key)
                if lora_value not in (None, "") and merged[style_key].get(lora_key) in (None, ""):
                    merged[style_key][lora_key] = lora_value

        return merged

    def _prune_entry(self, file_path: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        pruned: Dict[str, Any] = {
            "file_path": file_path,
            "file_name": Path(file_path).name,
            "pipeline": self._compact_pipeline(entry.get("pipeline")),
        }

        for key in ("date_taken", "date_taken_utc"):
            if entry.get(key) not in (None, ""):
                pruned[key] = entry.get(key)

        compact_gps = self._compact_gps(entry.get("gps"))
        if compact_gps:
            pruned["gps"] = compact_gps

        compact_location = self._compact_location(entry.get("location"))
        if compact_location:
            pruned["location"] = compact_location

        compact_derivatives = self._compact_derivatives(entry.get("derivatives"))
        if compact_derivatives:
            pruned["derivatives"] = compact_derivatives

        compact_watermark_ref = self._compact_watermark_ref(entry.get("watermark_ref"))
        if compact_watermark_ref:
            pruned["watermark_ref"] = compact_watermark_ref

        merged_outputs = self._merge_lora_generations_into_watermarked_outputs(entry)
        compact_outputs = self._compact_watermarked_outputs(merged_outputs)
        if compact_outputs:
            pruned["watermarked_outputs"] = compact_outputs

        return pruned

    def _is_under_source_root(self, file_path: str, source_root: Path) -> bool:
        try:
            Path(file_path).resolve().relative_to(source_root.resolve())
            return True
        except Exception:
            return False

    def prune_to_minimal(
        self,
        source_root: Optional[str] = None,
        drop_missing_files: bool = False,
    ) -> Dict[str, int]:
        stats = {
            "entries_before": len(self.data),
            "entries_after": 0,
            "removed_non_source": 0,
            "removed_missing": 0,
            "pruned_entries": 0,
        }

        source_root_path = Path(source_root).resolve() if source_root else None
        new_data: Dict[str, Dict[str, Any]] = {}

        for file_path, entry in list(self.data.items()):
            if source_root_path and not self._is_under_source_root(file_path, source_root_path):
                stats["removed_non_source"] += 1
                continue

            if drop_missing_files and not Path(file_path).exists():
                stats["removed_missing"] += 1
                continue

            pruned = self._prune_entry(file_path, entry if isinstance(entry, dict) else {})
            new_data[file_path] = pruned
            if pruned != entry:
                stats["pruned_entries"] += 1

        self.data = new_data
        stats["entries_after"] = len(self.data)
        return stats

    # ---------- Entry Management ----------
    def ensure_entry(self, file_path: str) -> Dict[str, Any]:
        if file_path not in self.data:
            p = Path(file_path)
            self.data[file_path] = {
                "file_path": file_path,
                "file_name": p.name,
                "pipeline": {
                    "stages": [],
                    "timestamps": {},
                    "last_updated": utc_now_iso_z()
                }
            }
        else:
            # Update last_updated timestamp on any access
            self.data[file_path].setdefault("pipeline", {}).setdefault("timestamps", {})
            self.data[file_path]["pipeline"]["last_updated"] = utc_now_iso_z()
        return self.data[file_path]

    def mark_stage(self, file_path: str, stage: str) -> None:
        entry = self.ensure_entry(file_path)
        stages = entry.setdefault("pipeline", {}).setdefault("stages", [])
        if stage not in stages:
            stages.append(stage)
        entry.setdefault("pipeline", {}).setdefault("timestamps", {})[stage] = utc_now_iso_z()

    def update_entry(self, file_path: str, patch: Dict[str, Any], stage: Optional[str] = None, save: Optional[bool] = None, source_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Update entry. If source_path is provided, this is a derivative and will be stored
        under the source entry instead of as a separate top-level entry.
        """
        # If this is a derivative (has source_path), store under source entry
        if source_path and source_path != file_path:
            source_entry = self.ensure_entry(source_path)
            
            # Determine derivative type and store accordingly
            if patch.get('type') == 'lora_watermarked':
                # Watermarked LoRA output
                if 'watermarked_outputs' not in source_entry:
                    source_entry['watermarked_outputs'] = {}
                lora_style = patch.get('lora', {}).get('style', 'unknown')
                source_entry['watermarked_outputs'][lora_style] = {
                    'path': file_path,
                    'timestamp': patch.get('watermark', {}).get('applied_at')
                }
            elif patch.get('type') in ['lora_processed']:
                # LoRA processed output
                if 'lora_outputs' not in source_entry:
                    source_entry['lora_outputs'] = {}
                lora_style = patch.get('lora', {}).get('style', 'unknown')
                source_entry['lora_outputs'][lora_style] = {
                    'path': file_path,
                    'timestamp': patch.get('lora', {}).get('timestamp')
                }
            elif patch.get('type') in ['watermarked', 'preprocessed']:
                # Regular watermarked or preprocessed - store under derivatives
                if 'derivatives' not in source_entry:
                    source_entry['derivatives'] = {}
                source_entry['derivatives'][patch.get('type')] = {
                    'path': file_path,
                    'timestamp': utc_now_iso_z()
                }
            
            if stage:
                self.mark_stage(source_path, stage)
            self.data[source_path] = self._prune_entry(source_path, source_entry)
            if save is None:
                save = self.auto_save
            if save:
                self.save()
            return self.data[source_path]
        
        # Normal top-level entry (source image)
        entry = self.ensure_entry(file_path)
        # COMPLETE REPLACEMENT: overwrite values, don't merge dicts
        # This ensures old fields get removed when schema changes
        for k, v in patch.items():
            entry[k] = v
        if stage:
            self.mark_stage(file_path, stage)
        self.data[file_path] = self._prune_entry(file_path, entry)
        if save is None:
            save = self.auto_save
        if save:
            self.save()
        return self.data[file_path]

    def update_section(self, file_path: str, section: str, section_data: Dict[str, Any], stage: Optional[str] = None, save: Optional[bool] = None) -> Dict[str, Any]:
        entry = self.ensure_entry(file_path)
        existing = entry.get(section)
        if isinstance(existing, dict):
            existing.update(section_data)
            entry[section] = existing
        else:
            entry[section] = section_data
        if stage:
            self.mark_stage(file_path, stage)
        self.data[file_path] = self._prune_entry(file_path, entry)
        if save is None:
            save = self.auto_save
        if save:
            self.save()
        return self.data[file_path]

    # ---------- Query Helpers ----------
    def get(self, file_path: str) -> Optional[Dict[str, Any]]:
        return self.data.get(file_path)

    def has_stage(self, file_path: str, stage: str) -> bool:
        entry = self.get(file_path)
        if not entry:
            return False
        return stage in entry.get("pipeline", {}).get("stages", [])

    def list_paths(self) -> Dict[str, Dict[str, Any]]:
        return self.data

__all__ = ["MasterStore"]
