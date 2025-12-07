#!/usr/bin/env python3
"""
Re-enhance Location Watermarks

This script:
1. Re-geocodes images using the new Photon provider (better POI accuracy)
2. Clears old Ollama enhancements that may have hallucinated from bad geocoding
3. Re-runs Ollama enhancement with accurate location data
4. Re-watermarks the images with correct information

Usage:
  # Re-enhance specific image
  python3 debug/re_enhance_locations.py --image IMG_5431

  # Re-enhance all images in an album
  python3 debug/re_enhance_locations.py --album Tokyo

  # Re-enhance all images in a city (where geocoding may have been inaccurate)
  python3 debug/re_enhance_locations.py --city Kelowna

  # Dry run (show what would be updated without making changes)
  python3 debug/re_enhance_locations.py --city Kelowna --dry-run
"""
import sys
import json
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.master_store import MasterStore
from core.geo_extractor import GeoExtractor
from core.ollama_location_enhancer import LocationEnhancementCache
from core.watermark_applicator import WatermarkApplicator


def re_geocode_image(master_store: MasterStore, extractor: GeoExtractor, 
                      image_path: str, dry_run: bool = False) -> bool:
    """Re-geocode a single image with new provider (Photon)"""
    entry = master_store.get(image_path)
    if not entry:
        print(f"❌ Image not found in master store: {image_path}")
        return False
    
    # Get GPS coordinates
    gps = entry.get('gps')
    if not gps or not gps.get('lat') or not gps.get('lon'):
        print(f"⚠️  No GPS data: {image_path}")
        return False
    
    lat = gps['lat']
    lon = gps['lon']
    
    # Get current location data
    current_location = entry.get('location', {})
    current_name = current_location.get('name') or current_location.get('display_name', '').split(',')[0]
    
    print(f"\n📍 {image_path}")
    print(f"   Current: {current_name or 'Unknown'}")
    
    if dry_run:
        print(f"   [DRY RUN] Would re-geocode: {lat:.6f}, {lon:.6f}")
        return True
    
    # Force fresh geocode (bypass cache)
    cache_key = f"{lat:.6f},{lon:.6f}"
    if cache_key in extractor.cache:
        del extractor.cache[cache_key]
    
    # Re-geocode with new provider (Photon + fallbacks)
    new_location = extractor.reverse_geocode(lat, lon)
    
    if not new_location:
        print(f"   ❌ Re-geocoding failed")
        return False
    
    new_name = new_location.get('name') or new_location.get('display_name', '').split(',')[0]
    provider = new_location.get('provider', 'unknown')
    poi_found = new_location.get('poi_found', False)
    
    print(f"   New ({provider}): {new_name} {'🏢 POI!' if poi_found else ''}")
    
    # Update master store
    formatted = extractor.format_location(new_location)
    master_store.upsert(image_path, {
        'location': new_location,
        'location_formatted': formatted
    })
    
    return True


def clear_ollama_enhancement(master_store: MasterStore, image_path: str, 
                              dry_run: bool = False) -> bool:
    """Clear old Ollama enhancement that may have hallucinated"""
    entry = master_store.get(image_path)
    if not entry:
        return False
    
    location = entry.get('location', {})
    if not location.get('ollama_enhanced'):
        return False
    
    if dry_run:
        print(f"   [DRY RUN] Would clear Ollama enhancement")
        return True
    
    # Remove ollama_enhanced field
    del location['ollama_enhanced']
    master_store.upsert(image_path, {'location': location})
    print(f"   🗑️  Cleared old Ollama enhancement")
    return True


def re_enhance_with_ollama(master_store: MasterStore, cache: LocationEnhancementCache,
                             image_path: str, dry_run: bool = False) -> bool:
    """Re-run Ollama enhancement with accurate location data"""
    entry = master_store.get(image_path)
    if not entry:
        return False
    
    location = entry.get('location', {})
    if not location:
        return False
    
    if dry_run:
        print(f"   [DRY RUN] Would re-enhance with Ollama")
        return True
    
    # Get Ollama enhancement
    enhanced = cache.get(image_path)
    if not enhanced:
        # Try to enhance
        formatted = entry.get('location_formatted', '')
        if formatted and formatted != 'Unknown Location':
            try:
                # This will call Ollama and store in master.json
                enhanced = cache.enhance_location(formatted, image_path)
                if enhanced:
                    print(f"   ✨ Ollama enhanced: {enhanced[:80]}...")
                    return True
            except Exception as e:
                print(f"   ❌ Ollama enhancement failed: {e}")
                return False
    else:
        print(f"   ✅ Already enhanced: {enhanced[:80]}...")
        return True
    
    return False


def main():
    parser = argparse.ArgumentParser(description='Re-enhance location watermarks with accurate geocoding')
    parser.add_argument('--image', help='Specific image to re-enhance (e.g., IMG_5431)')
    parser.add_argument('--album', help='Album to re-enhance (e.g., Tokyo)')
    parser.add_argument('--city', help='City to re-enhance (e.g., Kelowna)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--config', default='config/pipeline_config.json', help='Path to config file')
    
    args = parser.parse_args()
    
    if not any([args.image, args.album, args.city]):
        parser.error('Must specify --image, --album, or --city')
    
    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"❌ Config not found: {config_path}")
        return 1
    
    with open(config_path) as f:
        config = json.load(f)
    
    # Initialize components
    master_path = config.get('paths', {}).get('master_catalog')
    if not master_path:
        print("❌ master_catalog path not found in config")
        return 1
    
    master_store = MasterStore(master_path)
    extractor = GeoExtractor(config)
    cache = LocationEnhancementCache(master_store)
    
    # Find images to process
    images_to_process = []
    
    if args.image:
        # Find image by partial name
        for path in master_store.list_paths():
            if args.image in path:
                images_to_process.append(path)
    
    elif args.album:
        # Find all images in album
        for path in master_store.list_paths():
            if f'/{args.album}/' in path or path.startswith(args.album):
                images_to_process.append(path)
    
    elif args.city:
        # Find all images in city
        for path, entry in master_store.list_paths().items():
            location = entry.get('location', {})
            if location.get('city') == args.city:
                images_to_process.append(path)
    
    if not images_to_process:
        print(f"❌ No images found matching criteria")
        return 1
    
    print(f"\n{'=' * 80}")
    print(f"RE-ENHANCE LOCATION WATERMARKS")
    print(f"{'=' * 80}")
    print(f"\nFound {len(images_to_process)} images to process")
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
    print()
    
    # Process each image
    success_count = 0
    for image_path in images_to_process:
        # Step 1: Re-geocode with new provider
        if re_geocode_image(master_store, extractor, image_path, args.dry_run):
            # Step 2: Clear old Ollama enhancement
            clear_ollama_enhancement(master_store, image_path, args.dry_run)
            
            # Step 3: Re-enhance with Ollama
            re_enhance_with_ollama(master_store, cache, image_path, args.dry_run)
            
            success_count += 1
    
    print(f"\n{'=' * 80}")
    print(f"✅ Successfully processed {success_count}/{len(images_to_process)} images")
    if not args.dry_run:
        print(f"\n💡 Next step: Re-watermark the images")
        print(f"   python3 main.py stage watermark --album {args.album or args.city}")
    print(f"{'=' * 80}\n")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
