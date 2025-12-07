#!/usr/bin/env python3
"""
Purge watermark-related fields from master.json for clean geocode_sweep run.

Removes these fields:
- watermark_text (renamed from enhanced_watermark)
- ollama_generation
- ollama_enhanced_data

This allows geocode_sweep to regenerate all watermarks with the fixed prompt.
"""

import json
import sys
from pathlib import Path

def purge_watermark_fields(master_json_path: str = '/Volumes/MySSD/skicyclerun.i2i/pipeline/metadata/master.json'):
    """Remove all watermark-related fields from master.json"""
    
    master_path = Path(master_json_path)
    if not master_path.exists():
        print(f"❌ Master.json not found: {master_path}")
        return False
    
    # Load data
    print(f"📖 Reading {master_path}")
    with open(master_path, 'r') as f:
        data = json.load(f)
    
    # Count and purge fields
    total_entries = len(data)
    purged_watermark_text = 0
    purged_enhanced_watermark = 0  # Legacy field
    purged_ollama_generation = 0
    purged_ollama_enhanced_data = 0
    
    for path, entry in data.items():
        if 'watermark_text' in entry:
            del entry['watermark_text']
            purged_watermark_text += 1
        
        if 'enhanced_watermark' in entry:  # Legacy field from before rename
            del entry['enhanced_watermark']
            purged_enhanced_watermark += 1
        
        if 'ollama_generation' in entry:
            del entry['ollama_generation']
            purged_ollama_generation += 1
        
        if 'ollama_enhanced_data' in entry:
            del entry['ollama_enhanced_data']
            purged_ollama_enhanced_data += 1
    
    # Save cleaned data
    print(f"💾 Writing cleaned master.json...")
    with open(master_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    # Report
    print(f"\n✅ Purge complete!")
    print(f"📊 Total entries: {total_entries}")
    print(f"   - watermark_text removed: {purged_watermark_text}")
    if purged_enhanced_watermark > 0:
        print(f"   - enhanced_watermark (legacy) removed: {purged_enhanced_watermark}")
    print(f"   - ollama_generation removed: {purged_ollama_generation}")
    print(f"   - ollama_enhanced_data removed: {purged_ollama_enhanced_data}")
    
    total_purged = purged_watermark_text + purged_enhanced_watermark + purged_ollama_generation + purged_ollama_enhanced_data
    print(f"\n🧹 Total fields purged: {total_purged}")
    
    return True

if __name__ == '__main__':
    # Check for custom path argument
    if len(sys.argv) > 1:
        success = purge_watermark_fields(sys.argv[1])
    else:
        success = purge_watermark_fields()
    
    sys.exit(0 if success else 1)
