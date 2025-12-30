#!/usr/bin/env python3
"""
Backfill LoRA watermark metadata from lora_generations to lora_watermarks sections.

This script reads the master.json file and copies metadata from the 
lora_generations.{style} section to the corresponding lora_watermarks.{style} 
section for each image entry.

The metadata includes: seed, prompt, negative_prompt, num_inference_steps, 
guidance_scale, device, precision, source_image, and generated_at.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def backfill_lora_metadata(master_json_path):
    """
    Read master.json and backfill lora_watermarks metadata from lora_generations.
    
    Args:
        master_json_path: Path to master.json file
    """
    print(f"🔍 Reading master.json from: {master_json_path}")
    
    with open(master_json_path, 'r') as f:
        master_data = json.load(f)
    
    total_entries = len(master_data)
    updated_count = 0
    missing_generation_data = 0
    already_complete = 0
    
    print(f"📊 Processing {total_entries} entries...")
    print()
    
    for image_path, entry in master_data.items():
        # Skip if no lora_watermarks section
        lora_watermarks = entry.get('lora_watermarks', {})
        if not lora_watermarks:
            continue
        
        # Get lora_generations section
        lora_generations = entry.get('lora_generations', {})
        
        # Process each watermarked style
        for style_name, watermark_data in lora_watermarks.items():
            # Check if metadata fields are already populated
            has_metadata = watermark_data.get('seed') is not None
            
            if has_metadata:
                already_complete += 1
                continue
            
            # Look for corresponding generation data
            generation_data = lora_generations.get(style_name, {})
            
            if not generation_data:
                missing_generation_data += 1
                print(f"⚠️  No generation data found for {Path(image_path).name} - {style_name}")
                continue
            
            # Copy metadata fields
            metadata_fields = [
                'seed', 'prompt', 'negative_prompt', 'num_inference_steps',
                'guidance_scale', 'device', 'precision', 'source_image', 'generated_at'
            ]
            
            for field in metadata_fields:
                if field in generation_data:
                    watermark_data[field] = generation_data[field]
            
            updated_count += 1
            
            # Print progress every 100 updates
            if updated_count % 100 == 0:
                print(f"✅ Updated {updated_count} entries...")
    
    print()
    print(f"📈 Summary:")
    print(f"   Total entries: {total_entries}")
    print(f"   Updated: {updated_count}")
    print(f"   Already complete: {already_complete}")
    print(f"   Missing generation data: {missing_generation_data}")
    print()
    
    if updated_count > 0:
        # Create backup
        backup_path = str(master_json_path) + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"💾 Creating backup: {backup_path}")
        with open(backup_path, 'w') as f:
            json.dump(master_data, f, indent=2)
        
        # Write updated data
        print(f"💾 Writing updated master.json...")
        with open(master_json_path, 'w') as f:
            json.dump(master_data, f, indent=2)
        
        print(f"✅ Successfully backfilled {updated_count} lora_watermarks entries!")
    else:
        print("ℹ️  No updates needed - all entries are already complete.")
    
    return updated_count, missing_generation_data

def main():
    # Default path to master.json
    master_json_path = Path("/Volumes/MySSD/skicyclerun.i2i/pipeline/metadata/master.json")
    
    # Allow override from command line
    if len(sys.argv) > 1:
        master_json_path = Path(sys.argv[1])
    
    if not master_json_path.exists():
        print(f"❌ Error: master.json not found at {master_json_path}")
        print(f"Usage: {sys.argv[0]} [path/to/master.json]")
        sys.exit(1)
    
    try:
        updated, missing = backfill_lora_metadata(master_json_path)
        
        if missing > 0:
            print()
            print(f"⚠️  Warning: {missing} entries could not be backfilled due to missing generation data.")
            print(f"   These entries may need to be regenerated or manually updated.")
        
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
