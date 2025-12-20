#!/usr/bin/env python3
"""
Migrate watermarkLocationInfo.json into master.json

This script consolidates the separate watermark cache into master.json
using proper UPSERT to preserve all existing data.
"""
import json
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.master_store import MasterStore
from core.ollama_location_enhancer import LocationEnhancementCache
from utils.config_utils import resolve_config_placeholders


def main():
    print("=" * 80)
    print("MIGRATE WATERMARK CACHE TO MASTER.JSON")
    print("=" * 80)
    
    # Load config
    config_path = Path("config/pipeline_config.json")
    with open(config_path) as f:
        config = json.load(f)
    config = resolve_config_placeholders(config)
    
    # Paths
    metadata_dir = Path(config['paths']['metadata_dir'])
    old_cache_path = metadata_dir / 'watermarkLocationInfo.json'
    master_path = config['paths']['master_catalog']
    
    if not old_cache_path.exists():
        print(f"\n❌ No old cache file found at: {old_cache_path}")
        print("   Nothing to migrate. Your data is safe!")
        return 0
    
    print(f"\n📂 Old cache: {old_cache_path}")
    print(f"📂 Master store: {master_path}")
    
    # Load old cache
    print(f"\n📥 Loading old watermarkLocationInfo.json...")
    with open(old_cache_path) as f:
        old_cache = json.load(f)
    
    print(f"   Found {len(old_cache)} entries")
    
    # Load master store
    print(f"\n📥 Loading master.json...")
    master_store = MasterStore(master_path, auto_save=False)
    print(f"   Found {len(master_store.data)} total entries")
    
    # Migrate using UPSERT
    print(f"\n🔄 Migrating with UPSERT (preserves existing data)...")
    cache = LocationEnhancementCache(master_store)
    
    migrated = 0
    skipped = 0
    
    for image_path, enhancement in old_cache.items():
        # Check if this image exists in master.json
        if image_path in master_store.data:
            # UPSERT enhancement
            cache.set(image_path, enhancement)
            migrated += 1
            if migrated % 50 == 0:
                print(f"   Migrated {migrated}/{len(old_cache)}...")
        else:
            print(f"   ⚠️  Skipping {Path(image_path).name} (not in master.json)")
            skipped += 1
    
    # Save master.json
    print(f"\n💾 Saving master.json...")
    master_store.save()
    
    # Backup old cache
    backup_path = old_cache_path.with_suffix('.json.backup')
    print(f"\n📦 Backing up old cache to: {backup_path}")
    old_cache_path.rename(backup_path)
    
    print("\n" + "=" * 80)
    print("MIGRATION COMPLETE")
    print("=" * 80)
    print(f"\n📋 SUMMARY:")
    print(f"   ✅ Migrated: {migrated} entries")
    print(f"   ⚠️  Skipped: {skipped} entries (not in master.json)")
    print(f"   📦 Backup: {backup_path}")
    print(f"\n💡 All Ollama enhancements now in master.json under location.ollama_enhanced")
    print(f"   You can safely delete {backup_path} after verifying migration")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
