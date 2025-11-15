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

    # ---------- Entry Management ----------
    def ensure_entry(self, file_path: str) -> Dict[str, Any]:
        if file_path not in self.data:
            p = Path(file_path)
            self.data[file_path] = {
                "file_path": file_path,
                "file_name": p.name,
                "created_at": utc_now_iso_z(),
                "pipeline": {"stages": []}
            }
        return self.data[file_path]

    def mark_stage(self, file_path: str, stage: str) -> None:
        entry = self.ensure_entry(file_path)
        stages = entry.setdefault("pipeline", {}).setdefault("stages", [])
        if stage not in stages:
            stages.append(stage)
        entry.setdefault("pipeline", {}).setdefault("timestamps", {})[stage] = utc_now_iso_z()

    def update_entry(self, file_path: str, patch: Dict[str, Any], stage: Optional[str] = None, save: Optional[bool] = None) -> Dict[str, Any]:
        entry = self.ensure_entry(file_path)
        # shallow merge & nested dict merge
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(entry.get(k), dict):
                entry[k].update(v)
            else:
                entry[k] = v
        if stage:
            self.mark_stage(file_path, stage)
        if save is None:
            save = self.auto_save
        if save:
            self.save()
        return entry

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
        if save is None:
            save = self.auto_save
        if save:
            self.save()
        return entry

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
