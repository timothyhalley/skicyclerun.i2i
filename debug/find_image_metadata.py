#!/usr/bin/env python3
"""
Debug Tool: Find specific image in master store

Usage: python debug/find_image_metadata.py IMG_4668
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.master_store import MasterStore
from utils.config_utils import resolve_config_placeholders

# Load config
config_path = Path(__file__).parent.parent / 'config' / 'pipeline_config.json'
with open(config_path) as f:
    raw = json.load(f)
    config = resolve_config_placeholders(raw)

master_path = config.get('paths', {}).get('master_catalog')
print(f"📁 Master store: {master_path}\n")

store = MasterStore(master_path)
entries = store.list_paths()

# Search term from command line
search = sys.argv[1] if len(sys.argv) > 1 else "IMG_4668"
print(f"🔍 Searching for: {search}\n")

matches = []
for path, entry in entries.items():
    if search in path or search in Path(path).stem:
        matches.append((path, entry))

if not matches:
    print(f"❌ No matches found for '{search}'")
    print(f"\n💡 Hint: Check if image exists in albums/ or scaled/ directories")
else:
    print(f"✅ Found {len(matches)} match(es):\n")
    for path, entry in matches:
        print(f"  Path: {path}")
        print(f"  Stem: {Path(path).stem}")
        print(f"  Stages: {entry.get('pipeline', {}).get('stages', [])}")
        print(f"  Location: {entry.get('location_formatted', 'N/A')}")
        
        # Check if it has the required metadata
        has_location = 'location_formatted' in entry
        has_exif = 'exif' in entry
        has_gps = 'gps' in entry
        
        print(f"  Has location: {has_location}")
        print(f"  Has EXIF: {has_exif}")
        print(f"  Has GPS: {has_gps}")
        
        if has_gps:
            gps = entry.get('gps', {})
            print(f"  GPS: {gps.get('latitude')}, {gps.get('longitude')}")
        
        print()
