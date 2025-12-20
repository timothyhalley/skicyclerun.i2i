#!/usr/bin/env python3
"""
Debug Tool: Master Store Inspector

Validates master.json is populated and shows sample metadata entries.
Used for debugging metadata lookup issues.

Usage: python debug/check_master_store.py
"""
import json
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.master_store import MasterStore

# Load config
config_path = Path(__file__).parent.parent / 'config' / 'pipeline_config.json'
with open(config_path) as f:
    config = json.load(f)

master_path = config.get('paths', {}).get('master_catalog')
print(f"📁 Master store path: {master_path}")

if not master_path or not Path(master_path).exists():
    print("❌ Master store file not found!")
    exit(1)

# Load it
store = MasterStore(master_path)
entries = store.list_paths()

print(f"\n📊 Total entries: {len(entries)}")

if len(entries) == 0:
    print("\n⚠️  Master store is EMPTY! You need to run metadata_extraction stage first.")
else:
    print(f"\n🔍 Sample entries (first 5):")
    for i, (key, val) in enumerate(list(entries.items())[:5]):
        print(f"\n  {i+1}. Path: {key}")
        print(f"     File: {Path(key).name}")
        print(f"     Stem: {Path(key).stem}")
        stages = val.get('pipeline', {}).get('stages', [])
        print(f"     Stages: {stages}")
        if 'location_formatted' in val:
            print(f"     Location: {val['location_formatted']}")

print(f"\n✅ Done")
