#!/usr/bin/env python3
"""
Restructure master.json to simple album/image keying

OLD (bloated):
  Full absolute paths for every derivative file

NEW (clean):
  Album/image relative keys with subkeys for each process

Example:
  "2023-01-Singapore/IMG_1065.jpeg": {
    "exif": {...},
    "gps": {...},
    "location": {...},
    "lora": {
      "Afremov": {...},
      "Gorillaz": {...}
    },
    "watermark": {...},
    "deployment": {...}
  }
"""
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config_utils import resolve_config_placeholders


def get_album_image_key(file_path: str, lib_root: str) -> str:
    """Extract album/image key from full path"""
    path = Path(file_path)
    
    # Try to find album folder in path
    parts = path.parts
    
    # Look for albums folder (could be 'albums' or 'pipeline/albums')
    if 'albums' in parts:
        idx = parts.index('albums')
        if idx + 2 <= len(parts):  # albums/album_name/IMG_1065.jpeg or just albums/IMG_1065.jpeg
            # Check if there's an album subfolder
            if idx + 2 < len(parts):
                # albums/AlbumName/image.jpeg
                return f"{parts[idx+1]}/{parts[-1]}"
            else:
                # albums/image.jpeg (no album subfolder)
                return parts[-1]
    
    # Fallback: just use filename
    return path.name


def restructure_master_json(master_path: str, lib_root: str, dry_run: bool = False):
    """Restructure master.json to use album/image keys"""
    
    print("=" * 80)
    print("RESTRUCTURE MASTER.JSON")
    print("=" * 80)
    print(f"\n📂 Master file: {master_path}")
    print(f"📦 Lib root: {lib_root}")
    
    # Load old master.json
    with open(master_path) as f:
        old_data = json.load(f)
    
    print(f"\n📊 Old structure: {len(old_data)} entries")
    
    # Build new structure
    new_data = {}
    
    # Track statistics
    originals = 0
    derivatives = 0
    
    for old_path, old_entry in old_data.items():
        # Determine if this is an original or derivative
        # Original files are in pipeline/albums/ folder
        is_original = '/albums/' in old_path and ('scaled' not in old_path and 
                                                    'lora_processed' not in old_path and 
                                                    'lora_final' not in old_path and
                                                    'preprocessed' not in old_path and
                                                    'watermarked' not in old_path)
        
        if is_original:
            originals += 1
            
            # Extract album/image key
            key = get_album_image_key(old_path, lib_root)
            
            # Initialize new entry if doesn't exist
            if key not in new_data:
                new_data[key] = {
                    "file_name": Path(old_path).name,
                    "exif": {},
                    "gps": {},
                    "location": {},
                    "lora": {},
                    "watermark": {},
                    "deployment": {}
                }
            
            # Copy core metadata (comprehensive EXIF and all fields)
            if 'exif' in old_entry:
                new_data[key]['exif'] = old_entry['exif']
            
            if 'gps' in old_entry:
                new_data[key]['gps'] = old_entry['gps']
            
            if 'gps_coordinates' in old_entry:
                new_data[key]['gps_coordinates'] = old_entry['gps_coordinates']
            
            if 'location' in old_entry:
                new_data[key]['location'] = old_entry['location']
            
            if 'location_formatted' in old_entry:
                new_data[key]['location_formatted'] = old_entry['location_formatted']
            
            if 'heading' in old_entry:
                new_data[key]['heading'] = old_entry['heading']
            
            if 'landmarks' in old_entry:
                new_data[key]['landmarks'] = old_entry['landmarks']
            
            # Copy date fields
            if 'date_taken' in old_entry:
                new_data[key]['date_taken'] = old_entry['date_taken']
            
            if 'date_taken_utc' in old_entry:
                new_data[key]['date_taken_utc'] = old_entry['date_taken_utc']
            
            if 'timestamp' in old_entry:
                new_data[key]['timestamp'] = old_entry['timestamp']
        
        else:
            derivatives += 1
            
            # Handle derivative files (LoRA, watermarked, etc)
            source_path = old_entry.get('source_path')
            if source_path:
                source_key = get_album_image_key(source_path, lib_root)
                
                if source_key not in new_data:
                    new_data[source_key] = {
                        "file_name": Path(source_path).name,
                        "exif": {},
                        "gps": {},
                        "location": {},
                        "lora": {},
                        "watermark": {},
                        "deployment": {}
                    }
                
                # Detect type from path
                if 'lora_processed' in old_path:
                    # Extract LoRA style from filename
                    # IMG_1065_Afremov_timestamp.webp
                    stem = Path(old_path).stem
                    parts = stem.split('_')
                    if len(parts) >= 2:
                        lora_style = parts[1]
                        
                        if 'lora' in old_entry:
                            new_data[source_key]['lora'][lora_style] = old_entry['lora']
                        else:
                            new_data[source_key]['lora'][lora_style] = {
                                "output_path": old_path,
                                "processed": True
                            }
                
                elif 'watermarked_final' in old_path:
                    if 'watermark' in old_entry:
                        new_data[source_key]['watermark'] = old_entry['watermark']
                
                elif 'deployment' in old_entry:
                    new_data[source_key]['deployment'] = old_entry['deployment']
    
    print(f"\n📊 New structure: {len(new_data)} images")
    print(f"   Original files: {originals}")
    print(f"   Derivative files: {derivatives}")
    
    # Show sample entries
    print(f"\n📋 Sample entries:")
    for i, (key, entry) in enumerate(list(new_data.items())[:3], 1):
        print(f"\n{i}. {key}")
        print(f"   exif: {bool(entry.get('exif'))}")
        print(f"   gps: {bool(entry.get('gps'))}")
        print(f"   location: {bool(entry.get('location'))}")
        print(f"   lora styles: {list(entry.get('lora', {}).keys())}")
        print(f"   watermark: {bool(entry.get('watermark'))}")
    
    if dry_run:
        print(f"\n🔍 DRY RUN - No changes made")
        return
    
    # Backup old file
    backup_path = master_path + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"\n💾 Backing up old master.json to: {backup_path}")
    with open(backup_path, 'w') as f:
        json.dump(old_data, f, indent=2)
    
    # Write new structure
    print(f"\n💾 Writing new master.json...")
    with open(master_path, 'w') as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ RESTRUCTURE COMPLETE")
    print(f"   New entries: {len(new_data)}")
    print(f"   Backup: {backup_path}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Restructure master.json to album/image keys')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--config', default='config/pipeline_config.json', help='Config file')
    
    args = parser.parse_args()
    
    # Load config
    with open(args.config) as f:
        config = json.load(f)
    
    config = resolve_config_placeholders(config)
    
    master_path = config['paths']['master_catalog']
    lib_root = config['paths']['lib_root']
    
    restructure_master_json(master_path, lib_root, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
