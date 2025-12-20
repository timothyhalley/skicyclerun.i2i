#!/usr/bin/env python3
"""
Debug Tool: Watermark Metadata Lookup Tester

Tests metadata lookup logic for LoRA-processed images.
Simulates the basename extraction and master store search.

Usage: python debug/test_watermark_metadata.py
"""
import json
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.master_store import MasterStore

def test_metadata_lookup():
    """Test the metadata lookup for a LoRA-processed file"""
    
    # Load config
    config_path = Path(__file__).parent.parent / 'config' / 'pipeline_config.json'
    with open(config_path) as f:
        config = json.load(f)
    
    # Get master store path
    master_path = config.get('paths', {}).get('master_catalog')
    if not master_path:
        print("❌ No master_catalog path in config")
        return
    
    print(f"📁 Master store: {master_path}")
    master_store = MasterStore(master_path)
    
    # Show sample entries
    entries = master_store.list_paths()
    print(f"\n📊 Total entries in master store: {len(entries)}")
    
    # Show first few keys
    print("\n🔍 Sample entries:")
    for i, (key, val) in enumerate(list(entries.items())[:3]):
        print(f"\n  {i+1}. Key: {key}")
        print(f"     Stem: {Path(key).stem}")
        print(f"     Stages: {val.get('pipeline', {}).get('stages', [])}")
        print(f"     Location: {val.get('location_formatted', 'NOT SET')}")
    
    # Test a specific LoRA filename pattern
    print("\n" + "="*80)
    print("🧪 Testing LoRA filename parsing:")
    
    test_lora_name = "20170112_100724_GorillazStyle_12345678.webp"
    print(f"\n   LoRA file: {test_lora_name}")
    
    # Parse like postprocess_lora.py does
    filename_base = Path(test_lora_name).stem
    parts = filename_base.rsplit('_', 2)
    
    print(f"   Parsed parts: {parts}")
    
    if len(parts) == 3 and parts[-1].isdigit() and len(parts[-1]) == 8:
        original_base = parts[0]
        style = parts[1]
        timestamp = parts[2]
        print(f"   ✓ Original base: {original_base}")
        print(f"   ✓ Style: {style}")
        print(f"   ✓ Timestamp: {timestamp}")
    else:
        original_base = filename_base
        print(f"   ✗ Could not parse, using full stem: {original_base}")
    
    # Search for matching entries
    print(f"\n🔍 Searching for stem '{original_base}' in master store...")
    found = []
    for fp, e in entries.items():
        if Path(fp).stem == original_base:
            found.append((fp, e))
    
    if found:
        print(f"\n✅ Found {len(found)} matching entries:")
        for fp, e in found:
            print(f"\n   Path: {fp}")
            print(f"   Stages: {e.get('pipeline', {}).get('stages', [])}")
            print(f"   Location: {e.get('location_formatted', 'NOT SET')}")
            print(f"   Date taken: {(e.get('exif') or {}).get('date_taken', 'NOT SET')}")
            print(f"   GPS: {e.get('gps', 'NOT SET')}")
            print(f"   Landmarks: {len(e.get('landmarks') or [])} items")
    else:
        print(f"\n❌ No entries found matching stem '{original_base}'")
        print("\n   Showing stems of first 5 entries for comparison:")
        for fp in list(entries.keys())[:5]:
            print(f"   - {Path(fp).stem}")

if __name__ == "__main__":
    test_metadata_lookup()
