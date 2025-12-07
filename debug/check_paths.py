#!/usr/bin/env python3
"""Quick diagnostic to see actual paths in master.json"""
import json
from pathlib import Path

master = Path('/Volumes/MySSD/skicyclerun.i2i/pipeline/metadata/master.json')
with open(master) as f:
    data = json.load(f)

print(f"Total entries: {len(data)}")
print("\nFirst 10 paths:")
for i, path in enumerate(list(data.keys())[:10], 1):
    print(f"{i}. {path}")
    
    # Check for key indicators
    indicators = []
    if '/albums/' in path:
        indicators.append("HAS /albums/")
    if 'scaled' in path:
        indicators.append("scaled")
    if 'lora_processed' in path:
        indicators.append("lora_processed")
    if 'lora_final' in path:
        indicators.append("lora_final")
    if 'watermarked' in path:
        indicators.append("watermarked")
    if 'preprocessed' in path:
        indicators.append("preprocessed")
    
    if indicators:
        print(f"   → {', '.join(indicators)}")
    else:
        print(f"   → LIKELY ORIGINAL")
