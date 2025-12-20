#!/usr/bin/env python3
"""
Simple debug tool to test Ollama vision LLM with custom prompts
Usage: python debug/test_ollama_prompt.py <image_path> <prompt_file.txt>
"""

import sys
import json
import base64
import requests
import time
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from io import BytesIO


def load_config():
    """Load pipeline config to get LLM settings"""
    config_path = Path(__file__).parent.parent / "config" / "pipeline_config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config['llm_image_analysis']


def encode_image(image_path: str) -> str:
    """Encode image as base64 for Ollama"""
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        
        # Resize if too large
        max_size = 1024
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Encode as JPEG then base64
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=85)
        img_bytes = buffered.getvalue()
        
        return base64.b64encode(img_bytes).decode("utf-8")


def extract_gps_from_exif(image_path: str) -> dict:
    """Extract GPS coordinates from image EXIF data"""
    try:
        with Image.open(image_path) as img:
            exif = img._getexif()
            if not exif:
                return {}
            
            # Find GPS info
            gps_info = None
            for tag, value in exif.items():
                decoded = TAGS.get(tag, tag)
                if decoded == "GPSInfo":
                    gps_info = value
                    break
            
            if not gps_info:
                return {}
            
            # Parse GPS data
            gps_data = {}
            for key in gps_info.keys():
                decode = GPSTAGS.get(key, key)
                gps_data[decode] = gps_info[key]
            
            # Convert GPS coordinates to decimal degrees
            def convert_to_degrees(value):
                """Convert GPS coordinates to decimal degrees"""
                d, m, s = value
                return float(d) + (float(m) / 60.0) + (float(s) / 3600.0)
            
            lat = None
            lon = None
            altitude = None
            
            if 'GPSLatitude' in gps_data and 'GPSLatitudeRef' in gps_data:
                lat = convert_to_degrees(gps_data['GPSLatitude'])
                if gps_data['GPSLatitudeRef'] != 'N':
                    lat = -lat
            
            if 'GPSLongitude' in gps_data and 'GPSLongitudeRef' in gps_data:
                lon = convert_to_degrees(gps_data['GPSLongitude'])
                if gps_data['GPSLongitudeRef'] != 'E':
                    lon = -lon
            
            if 'GPSAltitude' in gps_data:
                altitude = float(gps_data['GPSAltitude'])
                altitude_ref = gps_data.get('GPSAltitudeRef', 0)
                if altitude_ref == 1:
                    altitude = -altitude
            
            # Extract heading
            heading = None
            if 'GPSImgDirection' in gps_data:
                heading = float(gps_data['GPSImgDirection'])
            
            # Calculate cardinal direction from heading
            cardinal = None
            if heading is not None:
                directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
                index = int((heading + 22.5) / 45) % 8
                cardinal = directions[index]
            
            return {
                'lat': lat,
                'lon': lon,
                'altitude': altitude,
                'heading': heading,
                'cardinal': cardinal
            }
            
    except Exception as e:
        print(f"⚠️  Could not extract GPS from EXIF: {e}")
        return {}


def search_nearby_pois(lat: float, lon: float, radius_m: int = 100, max_retries: int = 3) -> list:
    """Search for nearby POIs using Overpass API with retry logic"""
    
    # Try multiple Overpass API instances
    overpass_urls = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.openstreetmap.fr/api/interpreter"
    ]
    
    # Simplified query - prioritize speed over completeness
    query = f"""
    [out:json][timeout:25];
    (
      nwr["tourism"](around:{radius_m},{lat},{lon});
      nwr["historic"](around:{radius_m},{lat},{lon});
      nwr["amenity"="clock"](around:{radius_m},{lat},{lon});
      nwr["man_made"="clock"](around:{radius_m},{lat},{lon});
    );
    out tags center;
    """
    
    for attempt in range(max_retries):
        for overpass_url in overpass_urls:
            try:
                print(f"   🔄 Attempt {attempt + 1}/{max_retries} using {overpass_url.split('//')[1].split('/')[0]}")
                response = requests.post(overpass_url, data=query, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    elements = data.get('elements', [])
                    
                    pois = []
                    for elem in elements[:10]:  # Limit to top 10
                        tags = elem.get('tags', {})
                        name = tags.get('name', 'Unnamed')
                        
                        # Skip unnamed POIs
                        if name == 'Unnamed':
                            continue
                        
                        # Get description/wikipedia/wikidata for context
                        description = tags.get('description', '')
                        wikipedia = tags.get('wikipedia', '')
                        wikidata = tags.get('wikidata', '')
                        heritage = tags.get('heritage', '')
                        start_date = tags.get('start_date', '')
                        
                        # Determine category
                        if 'tourism' in tags:
                            category = tags['tourism']
                        elif 'historic' in tags:
                            category = tags['historic']
                        elif tags.get('amenity') == 'clock' or tags.get('man_made') == 'clock':
                            category = 'historic_clock'
                        else:
                            category = 'landmark'
                        
                        poi_data = {
                            'name': name,
                            'category': category,
                            'source': 'overpass'
                        }
                        
                        # Add historical context if available
                        context_parts = []
                        if description:
                            context_parts.append(f"Description: {description}")
                        if start_date:
                            context_parts.append(f"Built: {start_date}")
                        if heritage:
                            context_parts.append(f"Heritage: {heritage}")
                        if wikipedia:
                            context_parts.append(f"Wikipedia: {wikipedia}")
                        
                        if context_parts:
                            poi_data['context'] = ' | '.join(context_parts)
                        
                        pois.append(poi_data)
                    
                    print(f"   ✅ Found {len(pois)} POIs")
                    return pois
                    
                elif response.status_code == 504:
                    print(f"   ⏳ Server timeout (504), trying next server...")
                    time.sleep(2)
                    continue
                else:
                    print(f"   ⚠️  Error {response.status_code}, trying next server...")
                    continue
                    
            except requests.exceptions.Timeout:
                print(f"   ⏳ Request timeout, trying next server...")
                time.sleep(2)
                continue
            except Exception as e:
                print(f"   ⚠️  Error: {e}, trying next server...")
                continue
        
        # Wait before next retry attempt
        if attempt < max_retries - 1:
            wait_time = (attempt + 1) * 3
            print(f"   💤 Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
    
    print(f"   ❌ All POI search attempts failed")
    return []


def geocode_location(lat: float, lon: float) -> dict:
    """Reverse geocode GPS coordinates to get location details"""
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        headers = {
            'User-Agent': 'SkiCycleRun-Debug/1.0'
        }
        
        # Try multiple zoom levels to find city - start specific, go broader if needed
        zoom_levels = [16, 14, 12, 10]
        best_result = {}
        
        for zoom in zoom_levels:
            params = {
                'lat': lat,
                'lon': lon,
                'format': 'json',
                'zoom': zoom,
                'addressdetails': 1
            }
            
            # Nominatim requires rate limiting (1 request per second)
            time.sleep(1.1)
            
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                address = data.get('address', {})
                
                # Extract location details
                city = (address.get('city') or 
                       address.get('town') or 
                       address.get('village') or 
                       address.get('hamlet') or
                       address.get('municipality'))
                
                # For mountain/resort areas, check for named features
                landmark = (address.get('tourism') or
                           address.get('leisure') or
                           address.get('natural') or
                           address.get('peak') or
                           data.get('name'))
                
                state = (address.get('state') or 
                        address.get('region') or
                        address.get('province'))
                
                country = address.get('country')
                
                road = address.get('road')
                display_name = data.get('display_name')
                
                osm_type = data.get('osm_type')
                category = data.get('category')
                place_type = data.get('type')
                
                result = {
                    'city': city,
                    'landmark': landmark,
                    'state': state,
                    'country': country,
                    'road': road,
                    'display_name': display_name,
                    'osm_type': osm_type,
                    'category': category,
                    'type': place_type,
                    'zoom': zoom
                }
                
                # Keep first successful result
                if not best_result:
                    best_result = result
                
                # If we found a city or landmark, we're done
                if city or landmark:
                    if city and landmark:
                        print(f"   ✓ Found city '{city}' and landmark '{landmark}' at zoom {zoom}")
                    elif city:
                        print(f"   ✓ Found city '{city}' at zoom {zoom}")
                    elif landmark:
                        print(f"   ✓ Found landmark '{landmark}' at zoom {zoom}")
                    return result
                else:
                    print(f"   ⚠️  No city/landmark at zoom {zoom}, trying broader...")
            else:
                print(f"   ⚠️  Geocoding failed at zoom {zoom}: {response.status_code}")
        
        # Return best result even if no city found
        if best_result:
            print(f"   ⚠️  Using result from zoom {best_result.get('zoom')} (limited data)")
        return best_result
            
    except Exception as e:
        print(f"⚠️  Geocoding error: {e}")
        return {}


def send_to_ollama(image_path: str, prompt_text: str, config: dict):
    """Send image + prompt to Ollama and return response"""
    endpoint = config.get('endpoint', 'http://localhost:11434')
    model = config.get('model', 'qwen3-vl:32b')
    timeout = config.get('timeout', 300)
    
    print(f"📡 Endpoint: {endpoint}")
    print(f"🤖 Model: {model}")
    print(f"⏱️  Timeout: {timeout}s")
    print(f"📷 Image: {image_path}")
    print(f"📝 Prompt length: {len(prompt_text)} chars")
    print("-" * 80)
    
    # Encode image
    base64_image = encode_image(image_path)
    
    # Build payload
    payload = {
        "model": model,
        "prompt": prompt_text,
        "images": [base64_image],
        "stream": False,
        "options": {
            "temperature": 0.2,
            "top_p": 0.8
        }
    }
    
    # Send request
    generate_url = f"{endpoint.rstrip('/')}/api/generate"
    print(f"🚀 Sending request to {generate_url}...")
    
    try:
        response = requests.post(generate_url, json=payload, timeout=timeout)
        
        if response.status_code == 200:
            result = response.json()
            raw_response = result.get('response', '').strip()
            
            print("✅ Response received:")
            print("=" * 80)
            print(raw_response)
            print("=" * 80)
            
            return raw_response
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            return None
            
    except requests.exceptions.Timeout:
        print(f"❌ Request timeout after {timeout}s")
        return None
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to Ollama at {endpoint}")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def main():
    if len(sys.argv) != 3:
        print("Usage: python debug/test_ollama_prompt.py <image_path> <prompt_file.txt>")
        print("\nExample:")
        print("  python debug/test_ollama_prompt.py pipeline/albums/photo.jpg debug/prompt.txt")
        sys.exit(1)
    
    image_path = sys.argv[1]
    prompt_file = sys.argv[2]
    
    # Validate inputs
    if not Path(image_path).exists():
        print(f"❌ Image not found: {image_path}")
        sys.exit(1)
    
    if not Path(prompt_file).exists():
        print(f"❌ Prompt file not found: {prompt_file}")
        sys.exit(1)
    
    # Extract GPS from image EXIF
    gps_data = extract_gps_from_exif(image_path)
    
    # Echo GPS coordinates to terminal
    print("=" * 80)
    print("📍 GPS COORDINATES FROM EXIF:")
    if gps_data.get('lat') is not None and gps_data.get('lon') is not None:
        print(f"   Latitude:  {gps_data['lat']}")
        print(f"   Longitude: {gps_data['lon']}")
        if gps_data.get('altitude') is not None:
            print(f"   Altitude:  {gps_data['altitude']}m")
        if gps_data.get('heading') is not None:
            print(f"   Heading:   {gps_data['heading']}° {gps_data.get('cardinal', '')}")
    else:
        print("   ⚠️  No GPS data found in image EXIF")
    print("=" * 80)
    print()
    
    # Geocode location if GPS available
    location_data = {}
    nearby_pois = []
    if gps_data.get('lat') and gps_data.get('lon'):
        print("🌍 Geocoding GPS coordinates...")
        location_data = geocode_location(gps_data['lat'], gps_data['lon'])
        if location_data:
            print(f"   City:     {location_data.get('city', 'N/A')}")
            print(f"   Landmark: {location_data.get('landmark', 'N/A')}")
            print(f"   State:    {location_data.get('state', 'N/A')}")
            print(f"   Country:  {location_data.get('country', 'N/A')}")
            print(f"   Road:     {location_data.get('road', 'N/A')}")
            print(f"   OSM:      {location_data.get('osm_type', 'N/A')} / {location_data.get('category', 'N/A')} / {location_data.get('type', 'N/A')}")
            print("=" * 80)
            print()
        
        # Search for nearby POIs
        print("🔍 Searching for nearby POIs (100m radius)...")
        nearby_pois = search_nearby_pois(gps_data['lat'], gps_data['lon'], radius_m=100)
        if nearby_pois:
            print(f"   Found {len(nearby_pois)} POIs:")
            for poi in nearby_pois:
                context = poi.get('context', '')
                if context:
                    print(f"     • {poi['name']} ({poi['category']})")
                    print(f"       {context}")
                else:
                    print(f"     • {poi['name']} ({poi['category']})")
        else:
            print("   No POIs found nearby")
        print("=" * 80)
        print()
    
    # Load config
    config = load_config()
    
    # Read prompt template
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_template = f.read().strip()
    
    # Replace all placeholders in prompt with GPS data and geocoded location data
    prompt_text = prompt_template.format(
        # GPS coordinates (multiple naming conventions)
        photo_gps_lat=gps_data.get('lat', 'N/A'),
        photo_gps_lon=gps_data.get('lon', 'N/A'),
        photo_gps_altitude=gps_data.get('altitude', 'N/A'),
        photo_latitude=gps_data.get('lat', 'N/A'),
        photo_longitude=gps_data.get('lon', 'N/A'),
        photo_altitude=gps_data.get('altitude', 'N/A'),
        gps_lat=gps_data.get('lat', 'N/A'),
        gps_lon=gps_data.get('lon', 'N/A'),
        gps_altitude=gps_data.get('altitude', 'N/A'),
        lat=gps_data.get('lat', 'N/A'),
        lon=gps_data.get('lon', 'N/A'),
        altitude=gps_data.get('altitude', 'N/A'),
        # Heading and cardinal direction
        photo_heading=gps_data.get('heading', 'N/A'),
        photo_cardinal=gps_data.get('cardinal', 'N/A'),
        # Location data from geocoding
        photo_city=location_data.get('city') or location_data.get('landmark', 'N/A'),
        photo_state=location_data.get('state', 'N/A'),
        photo_country=location_data.get('country', 'N/A'),
        photo_road_or_display_name=location_data.get('road') or location_data.get('display_name', 'N/A'),
        photo_osm_type=location_data.get('osm_type', 'N/A'),
        photo_category=location_data.get('category', 'N/A'),
        photo_type=location_data.get('type', 'N/A'),
        nearby_pois='; '.join([
            f"{poi['name']} ({poi['category']})" + (f" - {poi['context']}" if poi.get('context') else "")
            for poi in nearby_pois
        ]) if nearby_pois else 'none'
    )
    
    # Replace [model] placeholder in JSON template with actual model name
    prompt_text = prompt_text.replace('[model]', config.get('model', 'unknown'))
    
    # Save the actual prompt being sent for debugging
    debug_prompt_path = "/tmp/ollama_prompt_debug.txt"
    with open(debug_prompt_path, 'w', encoding='utf-8') as f:
        f.write(prompt_text)
    print(f"💾 Saved actual prompt to: {debug_prompt_path}")
    print()
    
    # Send to Ollama
    send_to_ollama(image_path, prompt_text, config)


if __name__ == "__main__":
    main()
