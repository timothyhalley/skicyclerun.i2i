#!/usr/bin/env python3
"""
Spot Check Geocoding Tool

Test geocoding lookup for specific lat/lon coordinates to verify accuracy.

Usage:
  python3 debug/spot_check_geocode.py 49.88717777777778 -119.42606388888889
  python3 debug/spot_check_geocode.py --image IMG_5431
"""
import json
import sys
import argparse
import requests
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config_utils import resolve_config_placeholders
from core.master_store import MasterStore


def reverse_geocode(lat: float, lon: float, use_cache: bool = True, use_photon: bool = False) -> dict:
    """Call geocoding API to reverse geocode coordinates."""
    # Check cache first
    if use_cache:
        config_path = Path("config/pipeline_config.json")
        with open(config_path) as f:
            config = json.load(f)
        config = resolve_config_placeholders(config)
        
        cache_path = Path(config['paths']['metadata_dir']) / 'geocode_cache.json'
        if cache_path.exists():
            with open(cache_path) as f:
                cache = json.load(f)
            
            cache_key = f"{lat},{lon}"
            if cache_key in cache:
                print("📦 Found in geocode cache")
                return cache[cache_key]
    
    if use_photon:
        # Call Photon API (better POI detection)
        print("🌐 Calling Photon API (Komoot - better POI detection)...")
        url = "https://photon.komoot.io/reverse"
        params = {
            'lat': lat,
            'lon': lon,
            'limit': 10,
            'radius': 0.05  # 50m radius
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        features = data.get('features', [])
        if not features:
            return {'error': 'No results from Photon'}
        
        # Look for POIs first
        for feature in features:
            props = feature.get('properties', {})
            osm_key = props.get('osm_key', '')
            name = props.get('name')
            
            if name and osm_key in ['amenity', 'shop', 'tourism', 'leisure']:
                print(f"   ✅ Found POI: {name} (type: {osm_key}={props.get('osm_value', '')})")
                # Convert to standard format
                return {
                    'display_name': name,
                    'name': name,
                    'address': {
                        'road': props.get('street'),
                        'house_number': props.get('housenumber'),
                        'suburb': props.get('district'),
                        'city': props.get('city'),
                        'state': props.get('state'),
                        'postcode': props.get('postcode'),
                        'country': props.get('country')
                    },
                    'osm_type': props.get('osm_type'),
                    'osm_id': props.get('osm_id'),
                    'type': props.get('osm_value') or props.get('type'),
                    'poi_found': True,
                    'provider': 'photon'
                }
        
        # No POI, use first result
        print(f"   ℹ️  No POI found, using first result")
        props = features[0].get('properties', {})
        return {
            'display_name': props.get('name', '') or f"{props.get('street', '')}, {props.get('city', '')}",
            'address': {
                'road': props.get('street'),
                'suburb': props.get('district'),
                'city': props.get('city'),
                'state': props.get('state'),
                'postcode': props.get('postcode'),
                'country': props.get('country')
            },
            'osm_type': props.get('osm_type'),
            'provider': 'photon'
        }
    else:
        # Call Nominatim API (original)
        print("🌐 Calling Nominatim API (fresh lookup)...")
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            'lat': lat,
            'lon': lon,
            'format': 'json',
            'addressdetails': 1,
            'extratags': 1,
            'namedetails': 1,
            'zoom': 18  # High detail
        }
        headers = {
            'User-Agent': 'SkiCycleRun-Pipeline/1.0'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        return response.json()


def format_location_display(location_data: dict) -> str:
    """Format location data for display."""
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("LOCATION DATA")
    lines.append("=" * 80)
    
    # Display name
    display_name = location_data.get('display_name', 'N/A')
    lines.append(f"\n📍 Display Name:")
    lines.append(f"   {display_name}")
    
    # Address components
    address = location_data.get('address', {})
    if address:
        lines.append(f"\n🏠 Address Components:")
        for key in ['road', 'suburb', 'neighbourhood', 'village', 'town', 'city', 
                    'county', 'state', 'postcode', 'country']:
            if key in address:
                lines.append(f"   {key:15s}: {address[key]}")
    
    # Name details
    namedetails = location_data.get('namedetails', {})
    if namedetails:
        lines.append(f"\n🌍 Name Variants:")
        for key, value in namedetails.items():
            lines.append(f"   {key:15s}: {value}")
    
    # Extra tags
    extratags = location_data.get('extratags', {})
    if extratags:
        lines.append(f"\n🏷️  Extra Tags:")
        for key, value in list(extratags.items())[:10]:  # Limit to first 10
            lines.append(f"   {key:15s}: {value}")
    
    # OSM info
    lines.append(f"\n🗺️  OpenStreetMap Info:")
    lines.append(f"   OSM Type: {location_data.get('osm_type', 'N/A')}")
    lines.append(f"   OSM ID: {location_data.get('osm_id', 'N/A')}")
    lines.append(f"   Place ID: {location_data.get('place_id', 'N/A')}")
    
    return "\n".join(lines)


def check_master_store(image_name: str):
    """Check what's stored in master.json for this image."""
    config_path = Path("config/pipeline_config.json")
    with open(config_path) as f:
        config = json.load(f)
    config = resolve_config_placeholders(config)
    
    master_path = config['paths']['master_catalog']
    master_store = MasterStore(master_path, auto_save=False)
    
    # Find image by name
    matches = []
    for path, entry in master_store.data.items():
        if image_name in path:
            matches.append((path, entry))
    
    if not matches:
        print(f"\n❌ No images found matching '{image_name}' in master.json")
        return None
    
    if len(matches) > 1:
        print(f"\n⚠️  Multiple images found matching '{image_name}':")
        for i, (path, _) in enumerate(matches, 1):
            print(f"   {i}. {path}")
        print("\nShowing first match:\n")
    
    path, entry = matches[0]
    print("\n" + "=" * 80)
    print(f"MASTER.JSON ENTRY: {Path(path).name}")
    print("=" * 80)
    
    # GPS coordinates - check both gps field and location.lat/lon
    gps = entry.get('gps', {})
    location = entry.get('location', {})
    
    if gps and gps.get('latitude') and gps.get('longitude'):
        print(f"\n📍 GPS Coordinates (from gps field):")
        print(f"   Latitude:  {gps.get('latitude')}")
        print(f"   Longitude: {gps.get('longitude')}")
        lat = gps.get('latitude')
        lon = gps.get('longitude')
    elif isinstance(location, dict) and location.get('lat') and location.get('lon'):
        print(f"\n📍 GPS Coordinates (from location field):")
        print(f"   Latitude:  {location.get('lat')}")
        print(f"   Longitude: {location.get('lon')}")
        lat = location.get('lat')
        lon = location.get('lon')
    else:
        print("\n❌ No GPS data in master.json")
        lat = lon = None
    # Location data
    if location:
        if isinstance(location, dict):
            print(f"\n🏠 Location (from master.json):")
            print(f"   Display Name: {location.get('display_name', 'N/A')}")
            
            address = location.get('address', {})
            if address:
                print(f"\n   Address:")
                for key in ['road', 'city', 'state', 'country']:
                    if key in address:
                        print(f"      {key}: {address[key]}")
            
            # Ollama enhanced
            ollama = location.get('ollama_enhanced', {})
            if ollama:
                print(f"\n   🤖 Ollama Enhanced:")
                print(f"      Watermark: {ollama.get('enhanced_watermark', 'N/A')}")
                print(f"      POI: {ollama.get('poi', 'N/A')}")
        else:
            print(f"\n🏠 Location: {location}")
    else:
        print("\n❌ No location data in master.json")
    
    return (lat, lon) if lat and lon else None


def main():
    parser = argparse.ArgumentParser(
        description="Spot check geocoding accuracy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Direct lat/lon lookup
  python3 debug/spot_check_geocode.py 49.88717777777778 -119.42606388888889
  
  # Check what's stored for an image
  python3 debug/spot_check_geocode.py --image IMG_5431
  
  # Check image AND do fresh lookup (bypass cache)
  python3 debug/spot_check_geocode.py --image IMG_5431 --fresh
        """
    )
    parser.add_argument('lat', nargs='?', type=float, help='Latitude')
    parser.add_argument('lon', nargs='?', type=float, help='Longitude')
    parser.add_argument('--image', help='Image name to check in master.json')
    parser.add_argument('--fresh', action='store_true', 
                       help='Force fresh API lookup (bypass cache)')
    parser.add_argument('--use-photon', action='store_true',
                       help='Use Photon API instead of Nominatim (better POI detection)')
    
    args = parser.parse_args()
    
    lat = args.lat
    lon = args.lon
    
    # If image specified, look it up first
    if args.image:
        coords = check_master_store(args.image)
        if coords and not (lat and lon):
            lat, lon = coords
    
    if not lat or not lon:
        print("\n❌ No coordinates provided or found")
        print("   Provide lat/lon as arguments or use --image to lookup from master.json")
        return 1
    
    # Do geocode lookup
    print(f"\n🔍 Reverse Geocoding: {lat}, {lon}")
    print(f"   Google Maps: https://www.google.com/maps?q={lat},{lon}")
    
    try:
        location_data = reverse_geocode(lat, lon, use_cache=not args.fresh, use_photon=args.use_photon)
        print(format_location_display(location_data))
        
        print("\n" + "=" * 80)
        print("✅ SPOT CHECK COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
