#!/usr/bin/env python3
"""
Location Display Name Analysis Tool with Ollama Enhancement

Analyzes location metadata from master.json and uses local Ollama LLM to:
1. Create intelligent, concise display names for watermarks
2. Extract points of interest (POI) and historical context
3. Save enhanced data to watermarkLocationInfo.json for pipeline use

Usage:
  python3 analyze_location_display.py              # Sample 10 per album (default)
  python3 analyze_location_display.py --all        # Process ALL images
  python3 analyze_location_display.py --sample 25  # Sample 25 per album
"""
import json
import os
import sys
import random
import argparse
from pathlib import Path
from collections import defaultdict

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config_utils import resolve_config_placeholders
from core.ollama_location_enhancer import OllamaLocationEnhancer, LocationEnhancementCache
from core.master_store import MasterStore

def load_config():
    """Load and resolve pipeline configuration."""
    config_path = Path("config/pipeline_config.json")
    with open(config_path) as f:
        return resolve_config_placeholders(json.load(f))

def load_master_store(config):
    """Load master.json metadata store."""
    master_path = config['paths']['master_catalog']
    
    if not Path(master_path).exists():
        print(f"❌ Master store not found at: {master_path}")
        return None
    
    with open(master_path) as f:
        return json.load(f)

def analyze_location_info(location_info):
    """Analyze a location_info dict and extract all available components."""
    if not location_info:
        return None
    
    # Check if location_info is a dict or string
    if isinstance(location_info, str):
        # Just a string, no structured data
        return {
            'display_name': location_info,
            'address': {},
            'namedetails': {},
            'country_code': '',
            'components': {
                'road': '', 'suburb': '', 'city': '', 'town': '', 'village': '',
                'county': '', 'state': '', 'country': '', 'postcode': ''
            },
            'english_name': '',
            'local_name': ''
        }
    
    analysis = {
        'display_name': location_info.get('display_name', ''),
        'address': location_info.get('address', {}),
        'namedetails': location_info.get('namedetails', {}),
        'country_code': location_info.get('address', {}).get('country_code', '').upper()
    }
    
    # Extract address components
    addr = analysis['address']
    analysis['components'] = {
        'road': addr.get('road', ''),
        'suburb': addr.get('suburb', ''),
        'city': addr.get('city', ''),
        'town': addr.get('town', ''),
        'village': addr.get('village', ''),
        'county': addr.get('county', ''),
        'state': addr.get('state', ''),
        'country': addr.get('country', ''),
        'postcode': addr.get('postcode', ''),
    }
    
    # Extract English name from namedetails
    namedetails = analysis['namedetails']
    analysis['english_name'] = namedetails.get('name:en', '')
    analysis['local_name'] = namedetails.get('name', '')
    
    return analysis

def is_generic_road_name(name):
    """Check if a name is a generic/boring road name vs a meaningful landmark."""
    if not name:
        return True
    
    name_lower = name.lower()
    
    # Skip generic road types
    generic_patterns = [
        'parkway', 'highway', 'freeway', 'boulevard', 'avenue', 'street',
        'road', 'drive', 'lane', 'way', 'trail', 'path', 'route',
        'mainline', 'forest service road', 'county road', 'state route'
    ]
    
    # If it's JUST a road type with no distinctive name, skip it
    for pattern in generic_patterns:
        if name_lower.endswith(f' {pattern}') or name_lower == pattern:
            # Exception: Famous roads/highways should be kept
            famous_roads = [
                'pacific coast highway', 'blue ridge parkway', 'route 66',
                'mulholland drive', 'lombard street', 'wall street',
                'fifth avenue', 'champs-élysées'
            ]
            if any(famous in name_lower for famous in famous_roads):
                return False
            return True
    
    return False

def format_optimal_display_name(analysis):
    """
    Formulate the optimal display name for watermarking.
    
    If no structured address components, parse from display_name string.
    
    Strategy:
    1. Use English name if available (from name:en) - usually a landmark
    2. Skip generic road names, prefer towns/cities/landmarks
    3. Include meaningful locality (suburb/neighborhood)
    4. Include city/town (ALWAYS - this is the key location)
    5. Include state/region for large countries (US, Canada, Australia, etc.)
    6. Include country for international photos
    7. Avoid duplication (e.g., "Singapore, Singapore")
    8. Keep concise but informative
    """
    if not analysis:
        return "Unknown Location"
    
    parts = []
    comp = analysis['components']
    country_code = analysis['country_code']
    
    # If no address components, parse from display_name
    has_components = any(comp.values())
    if not has_components:
        display_name = analysis.get('display_name', '')
        if display_name:
            # Parse: "Street, Neighborhood, City, County, State, Zip, Country"
            parts_list = [p.strip() for p in display_name.split(',')]
            if len(parts_list) >= 2:
                # Take second-to-last (usually city/state) and last (country)
                return f"{parts_list[-2]}, {parts_list[-1]}" if len(parts_list) >= 2 else parts_list[-1]
        return "Unknown Location"
    
    # Strategy 1: Use English name from namedetails (usually a landmark)
    if analysis['english_name'] and not is_generic_road_name(analysis['english_name']):
        parts.append(analysis['english_name'])
    # Strategy 2: Check if road name is meaningful (not generic)
    elif comp['road'] and not is_generic_road_name(comp['road']) and any(ord(c) < 128 for c in comp['road']):
        parts.append(comp['road'])
    # Strategy 3: Skip the first component if it's a road, use town/city instead
    # (We'll add city/town below, so just leave parts empty here)
    
    # Add locality (suburb/neighborhood) if available and not already included
    locality = comp['suburb'] or ''
    if locality and locality.lower() not in [p.lower() for p in parts]:
        if country_code in ['JP', 'CN', 'KR', 'TW']:
            # For CJK, only include if has Latin chars
            if any(c.isalpha() and ord(c) < 128 for c in locality):
                parts.append(locality)
        else:
            parts.append(locality)
    
    # Add city/town/village if not already included
    # Try in order: city -> town -> village -> county
    city = comp['city'] or comp['town'] or comp['village'] or comp['county']
    if city and city.lower() not in [p.lower() for p in parts]:
        if country_code in ['JP', 'CN', 'KR', 'TW']:
            # For CJK, only include if has Latin chars
            if any(c.isalpha() and ord(c) < 128 for c in city):
                parts.append(city)
        else:
            parts.append(city)
    
    # Add state for large countries (only if not same as country)
    if country_code in ['US', 'CA', 'AU', 'BR', 'IN', 'MX']:
        state = comp['state']
        if state and state.lower() not in [p.lower() for p in parts]:
            # For US states, use abbreviation if full name is long
            if country_code == 'US' and len(state) > 12:
                state_abbrev = {
                    'Florida': 'FL',
                    'California': 'CA',
                    'New York': 'NY',
                    'Texas': 'TX',
                    'Pennsylvania': 'PA',
                    'North Carolina': 'NC',
                    'South Carolina': 'SC',
                    'Massachusetts': 'MA',
                    'Washington': 'WA',
                    'Colorado': 'CO'
                }
                state = state_abbrev.get(state, state)
            parts.append(state)
    
    # Add country if not already included (avoid "Singapore, Singapore")
    country = comp['country']
    if country and country.lower() not in [p.lower() for p in parts]:
        # For CJK, use English country names
        if country_code in ['JP', 'CN', 'KR', 'TW']:
            country_map = {
                'JP': 'Japan',
                'CN': 'China',
                'KR': 'South Korea',
                'TW': 'Taiwan'
            }
            parts.append(country_map.get(country_code, country))
        else:
            parts.append(country)
    
    # Join with commas and remove any empty parts
    display = ', '.join(p for p in parts if p and p.strip())
    
    return display if display else "Unknown Location"

def sample_images_by_album(master_data, sample_size=10):
    """Sample random images from each album."""
    albums = defaultdict(list)
    
    # Group by album
    for image_path, metadata in master_data.items():
        # Extract album from path
        parts = Path(image_path).parts
        if 'albums' in parts:
            idx = parts.index('albums')
            if idx + 1 < len(parts):
                album = parts[idx + 1]
                albums[album].append((image_path, metadata))
    
    # Sample from each album
    sampled = {}
    for album, items in albums.items():
        sample = random.sample(items, min(sample_size, len(items)))
        sampled[album] = sample
    
    return sampled

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Analyze location metadata and enhance with Ollama LLM',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s              # Sample 10 images per album (default)
  %(prog)s --all        # Process ALL images
  %(prog)s --sample 25  # Sample 25 images per album
        """
    )
    parser.add_argument('--all', action='store_true', 
                       help='Process all images (no sampling)')
    parser.add_argument('--sample', type=int, default=10, metavar='N',
                       help='Sample N images per album (default: 10)')
    args = parser.parse_args()
    
    print("=" * 80)
    print("LOCATION DISPLAY NAME ANALYSIS WITH OLLAMA ENHANCEMENT")
    print("=" * 80)
    
    # Load config and master store
    config = load_config()
    master_data = load_master_store(config)
    
    if not master_data:
        return 1
    
    print(f"\n📊 Total images in master store: {len(master_data)}")
    
    # Initialize Ollama enhancer - use mixtral which you have installed
    print("🤖 Initializing Ollama enhancer (mixtral:8x7b on localhost:11434)")
    enhancer = OllamaLocationEnhancer(config, model="mixtral:8x7b")
    
    # Initialize cache using MasterStore (consolidated storage in master.json)
    master_path = config['paths']['master_catalog']
    master_store = MasterStore(master_path, auto_save=True)
    cache = LocationEnhancementCache(master_store)
    stats = cache.get_stats()
    print(f"💾 Storage: master.json (consolidated)")
    print(f"   Existing Ollama enhancements: {stats['total_entries']}\n")
    
    # Sample or process all images
    if args.all:
        # Process all images - group by album or folder structure
        albums = defaultdict(list)
        for image_path, metadata in master_data.items():
            parts = Path(image_path).parts
            # Try to find album folder - check for 'albums', 'lora_processed', or 'scaled'
            album = None
            for folder_name in ['albums', 'lora_processed', 'scaled']:
                if folder_name in parts:
                    idx = parts.index(folder_name)
                    if idx + 1 < len(parts):
                        album = parts[idx + 1]
                        break
            
            # If no album found, use parent directory name
            if not album:
                album = parts[-2] if len(parts) >= 2 else 'unknown'
            
            albums[album].append((image_path, metadata))
        sampled = dict(albums)
        print(f"📁 Albums/folders found: {len(sampled)}")
        print(f"🔥 Processing ALL images ({len(master_data)} total)\n")
    else:
        # Sample images by album
        sampled = sample_images_by_album(master_data, sample_size=args.sample)
        print(f"📁 Albums found: {len(sampled)}")
        print(f"🎲 Sampling {args.sample} random images per album\n")
    
    # Analyze each album
    for album_name in sorted(sampled.keys()):
        samples = sampled[album_name]
        
        print("=" * 80)
        print(f"📁 ALBUM: {album_name}")
        print(f"   Total images: {sum(1 for _, m in samples if m)}")
        print(f"   Sample size: {len(samples)}")
        print("=" * 80)
        
        for idx, (image_path, metadata) in enumerate(samples, 1):
            location_info = metadata.get('location')
            
            if not location_info:
                print(f"\n{idx}. {Path(image_path).name}")
                print(f"   ❌ No location metadata")
                continue
            
            # Debug: Check if location_info is a string (raw display_name) or dict
            if isinstance(location_info, str):
                # Location is just a string, not full geocoding data
                print(f"\n{idx}. {Path(image_path).name}")
                print(f"   ⚠️  Location is STRING only (not full geocoding): {location_info}")
                print(f"   🤖 OLLAMA ENHANCING with limited data...")
                # Create minimal structure for Ollama
                fake_location_info = {
                    'display_name': location_info,
                    'address': {},
                    'namedetails': {}
                }
                try:
                    enhanced = enhancer.enhance_location(fake_location_info)
                    cache.set(image_path, enhanced)
                    print(f"   ✅ OLLAMA ENHANCED:")
                    print(f"      Watermark: {enhanced['watermark_display_name']}")
                    if enhanced.get('notable_poi'):
                        print(f"      POI: {enhanced['notable_poi']}")
                    if enhanced.get('brief_history'):
                        print(f"      History: {enhanced['brief_history']}")
                except Exception as e:
                    print(f"   ❌ Ollama failed: {e}")
                continue
            
            analysis = analyze_location_info(location_info)
            optimal_name = format_optimal_display_name(analysis)
            
            print(f"\n{idx}. {Path(image_path).name}")
            print(f"   📍 Country: {analysis['country_code']}")
            
            # Show original display_name (FULL, no truncation)
            print(f"   🏷️  Original display_name:")
            print(f"      {analysis['display_name']}")
            
            # Show English name if available
            if analysis['english_name']:
                print(f"   🌍 English name (name:en): {analysis['english_name']}")
            
            # Show address components
            print(f"   🗺️  Address components:")
            comp = analysis['components']
            if comp['road']:
                print(f"      Road: {comp['road']}")
            if comp['suburb']:
                print(f"      Suburb/Neighborhood: {comp['suburb']}")
            if comp['village']:
                print(f"      Village: {comp['village']}")
            if comp['town']:
                print(f"      Town: {comp['town']}")
            if comp['city']:
                print(f"      City: {comp['city']}")
            if comp['county']:
                print(f"      County: {comp['county']}")
            if comp['state']:
                print(f"      State: {comp['state']}")
            if comp['country']:
                print(f"      Country: {comp['country']}")
            
            # Show heuristic proposed name
            print(f"   💡 HEURISTIC PROPOSED NAME:")
            print(f"      {optimal_name}")
            
            # Get or generate Ollama enhancement
            cached = cache.get(image_path)
            if cached:
                print(f"   ♻️  OLLAMA ENHANCED (from cache):")
                enhanced = cached
            else:
                print(f"   🤖 OLLAMA ENHANCING (calling LLM)...")
                try:
                    enhanced = enhancer.enhance_location(location_info)
                    cache.set(image_path, enhanced)
                    print(f"   ✅ OLLAMA ENHANCED:")
                except Exception as e:
                    print(f"   ❌ Ollama failed: {e}")
                    enhanced = {
                        'watermark_display_name': optimal_name,
                        'notable_poi': '',
                        'brief_history': ''
                    }
            
            print(f"      Display Name: {enhanced.get('display_name', 'N/A')}")
            if enhanced.get('display_name_en') and enhanced.get('display_name_en') != enhanced.get('display_name'):
                print(f"      Display Name (EN): {enhanced.get('display_name_en', 'N/A')}")
            
            print(f"      POI: {enhanced.get('poi', 'N/A')}")
            if enhanced.get('poi_en') and enhanced.get('poi_en') != enhanced.get('poi'):
                print(f"      POI (EN): {enhanced.get('poi_en', 'N/A')}")
            
            print(f"      History: {enhanced.get('history', 'N/A')}")
            print(f"      📍 Basic Watermark: {enhanced.get('basic_watermark', 'N/A')}")
            if enhanced.get('basic_watermark_en') and enhanced.get('basic_watermark_en') != enhanced.get('basic_watermark'):
                print(f"      📍 Basic Watermark (EN): {enhanced.get('basic_watermark_en', 'N/A')}")
            
            # Only show bilingual breakdown if languages differ
            original = enhanced.get('enhanced_watermark_original', '')
            english = enhanced.get('enhanced_watermark_english', '')
            
            if original and english and original != english:
                print(f"      ✨ Enhanced Watermark (Bilingual): {enhanced.get('enhanced_watermark', 'N/A')}")
                print(f"         🌏 Original: {original}")
                print(f"         🌐 English: {english}")
            else:
                print(f"      ✨ Enhanced Watermark: {enhanced.get('enhanced_watermark', 'N/A')}")
            
            # Show visual preview of watermark + copyright line
            # For bilingual, show original and english on same line separated by comma
            if original and english and original != english:
                watermark_line = f"{original}, {english}"
            else:
                watermark_line = enhanced.get('enhanced_watermark', 'N/A')
            
            # Build copyright line: {City, State/Country} ▲ SkiCycleRun © 2026
            # Try to get from comp first, then fallback to parsing display_name
            city = comp.get('city') or comp.get('town') or comp.get('village') or ''
            state = comp.get('state') or ''
            country = comp.get('country') or ''
            
            # Fallback: parse from display_name if components are empty
            if not city and not country:
                # Parse: "Street, Neighborhood, City, County, State, Zip, Country"
                parts = [p.strip() for p in analysis['display_name'].split(',')]
                if len(parts) >= 2:
                    # Filter out zip codes (5 digits or 5-4 format)
                    filtered_parts = [p for p in parts if not (p.replace('-', '').isdigit() and len(p.replace('-', '')) >= 5)]
                    
                    if filtered_parts:
                        # Last part is country
                        country = filtered_parts[-1] if filtered_parts[-1] else ''
                        # Second to last is usually state
                        if len(filtered_parts) >= 2:
                            state = filtered_parts[-2] if filtered_parts[-2] else ''
                        # Third to last is usually city
                        if len(filtered_parts) >= 3:
                            city = filtered_parts[-3] if filtered_parts[-3] else ''
            
            # Format copyright line
            if city and state and state != country:
                # US/Canada style: "New York, New York" or "Toronto, Ontario"
                copyright_line = f"{city}, {state}  ▲ SkiCycleRun © 2026"
            elif city and country:
                copyright_line = f"{city}, {country}  ▲ SkiCycleRun © 2026"
            elif city:
                copyright_line = f"{city}  ▲ SkiCycleRun © 2026"
            else:
                copyright_line = "▲ SkiCycleRun © 2026"
            
            # Check if watermark is redundant (contains same info as copyright)
            # Extract location parts from copyright line for comparison
            copyright_location = copyright_line.split('▲')[0].strip()
            
            # If watermark is just the location name (no actual landmarks), suppress it
            watermark_lower = watermark_line.lower()
            copyright_lower = copyright_location.lower()
            
            # Check if watermark essentially repeats the copyright location info
            is_redundant = (
                watermark_line == copyright_location or
                watermark_lower in copyright_lower or
                copyright_lower in watermark_lower or
                (city and city.lower() in watermark_lower and country and country.lower() in watermark_lower and ',' in watermark_line and len(watermark_line.split()) <= 3)
            )
            
            print(f"\n      📸 WATERMARK PREVIEW:")
            if not is_redundant:
                print(f"         {watermark_line}")
            print(f"         {copyright_line}")
        
        print()
    
    # Stats - no explicit save needed, MasterStore auto-saves on each upsert
    print("\n💾 Ollama enhancements saved to master.json (auto-save after each update)")
    stats = cache.get_stats()
    print(f"   ✅ Total enhanced entries in master.json: {stats['total_entries']}")
    
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print("\n📋 SUMMARY:")
    print(f"   • Total images analyzed: {sum(len(samples) for samples in sampled.values())}")
    print(f"   • Enhanced entries in master.json: {stats['total_entries']}")
    print(f"   • Storage: {stats['storage']}")
    print("\n💡 NEXT STEPS:")
    print("   1. Review the Ollama-enhanced display names above")
    print("   2. Run pipeline.py --stages post_lora_watermarking")
    print("   3. Watermarks will read enhanced data from master.json (location.ollama_enhanced)")
    print("   4. Re-run this tool anytime to add/update enhancements (UPSERT - no data loss)")
    print()

if __name__ == '__main__':
    sys.exit(main())
