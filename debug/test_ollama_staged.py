#!/usr/bin/env python3
"""
Staged LLM test - separate photo analysis from POI context integration
Usage: python debug/test_ollama_staged.py <image_path>
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


def scale_image_for_model(image_path: str, max_dim: int = 1024) -> tuple:
    """Scale image appropriately for LLM vision model
    
    Returns: (base64_image, original_width, original_height, is_panorama)
    """
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        orig_width, orig_height = img.size
        aspect_ratio = orig_width / orig_height
        
        # Detect panorama (aspect ratio > 2:1 or < 1:2)
        is_panorama = aspect_ratio > 2.0 or aspect_ratio < 0.5
        
        # For panoramas, use larger max dimension
        target_max = 1536 if is_panorama else max_dim
        
        if max(img.size) > target_max:
            ratio = target_max / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            scaled_size = img.size
        else:
            scaled_size = img.size
        
        # Encode to base64
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return base64_image, orig_width, orig_height, scaled_size, is_panorama


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
                d, m, s = value
                return float(d) + (float(m) / 60.0) + (float(s) / 3600.0)
            
            # Get latitude
            lat = None
            if 'GPSLatitude' in gps_data and 'GPSLatitudeRef' in gps_data:
                lat = convert_to_degrees(gps_data['GPSLatitude'])
                if gps_data['GPSLatitudeRef'] == 'S':
                    lat = -lat
            
            # Get longitude
            lon = None
            if 'GPSLongitude' in gps_data and 'GPSLongitudeRef' in gps_data:
                lon = convert_to_degrees(gps_data['GPSLongitude'])
                if gps_data['GPSLongitudeRef'] == 'W':
                    lon = -lon
            
            # Get altitude
            altitude = None
            if 'GPSAltitude' in gps_data:
                altitude = float(gps_data['GPSAltitude'])
            
            # Get heading (direction camera was pointing)
            heading = None
            cardinal = None
            if 'GPSImgDirection' in gps_data:
                heading = float(gps_data['GPSImgDirection'])
                # Convert heading to cardinal direction
                directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                            'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
                idx = int((heading + 11.25) / 22.5) % 16
                cardinal = directions[idx]
            
            return {
                'lat': lat,
                'lon': lon,
                'altitude': altitude,
                'heading': heading,
                'cardinal': cardinal
            }
            
    except Exception as e:
        print(f"⚠️  GPS extraction error: {e}")
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
                server_name = overpass_url.split('//')[1].split('/')[0]
                print(f"   🔄 Attempt {attempt + 1}/{max_retries} using {server_name}")
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
        headers = {'User-Agent': 'SkiCycleRun-Debug/1.0'}
        
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
            
            time.sleep(1.1)  # Rate limiting
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                address = data.get('address', {})
                
                city = (address.get('city') or address.get('town') or 
                       address.get('village') or address.get('hamlet') or
                       address.get('municipality'))
                
                landmark = (address.get('tourism') or address.get('leisure') or
                           address.get('natural') or address.get('peak') or
                           data.get('name'))
                
                state = (address.get('state') or address.get('region') or
                        address.get('province'))
                
                country = address.get('country')
                road = address.get('road')
                display_name = data.get('display_name')
                
                result = {
                    'city': city,
                    'landmark': landmark,
                    'state': state,
                    'country': country,
                    'road': road,
                    'display_name': display_name,
                    'zoom': zoom
                }
                
                if not best_result:
                    best_result = result
                
                if city or landmark:
                    return result
        
        return best_result
            
    except Exception as e:
        print(f"⚠️  Geocoding error: {e}")
        return {}


def analyze_photo_content(base64_image: str, config: dict) -> dict:
    """Stage 4: Quick photo analysis using lighter model for speed
    
    Fast analysis - just identify what's IN the photo
    """
    # Simpler, faster prompt
    prompt = """Describe what you see in JSON:
{
  "main_subject": "main thing in photo",
  "scene_type": "indoor/outdoor/urban/natural"
}"""
    
    endpoint = config.get('endpoint', 'http://localhost:11434')
    # Use lighter/faster model for Stage 4 quick analysis
    model = 'llava:7b'
    
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [base64_image],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "top_p": 0.9,
            "num_predict": 100  # Limit output length for speed
        }
    }
    
    try:
        response = requests.post(f"{endpoint}/api/generate", json=payload, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            raw_response = result.get('response', '').strip()
            
            # Explicitly close response to free resources
            response.close()
            
            # Try to parse JSON
            try:
                # Extract JSON from markdown code blocks if present
                if '```json' in raw_response:
                    json_str = raw_response.split('```json')[1].split('```')[0].strip()
                elif '```' in raw_response:
                    json_str = raw_response.split('```')[1].split('```')[0].strip()
                else:
                    json_str = raw_response
                
                return json.loads(json_str)
            except:
                return {"raw_response": raw_response}
        else:
            response.close()
            return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def main():
    if len(sys.argv) != 3:
        print("Usage: python debug/test_ollama_staged.py <image_path> <prompt_file.txt>")
        print("\nExample:")
        print("  python debug/test_ollama_staged.py pipeline/albums/photo.jpg debug/llm_prompt_simple.txt")
        sys.exit(1)
    
    image_path = sys.argv[1]
    prompt_file = sys.argv[2]
    
    if not Path(image_path).exists():
        print(f"❌ Image not found: {image_path}")
        sys.exit(1)
    
    if not Path(prompt_file).exists():
        print(f"❌ Prompt file not found: {prompt_file}")
        sys.exit(1)
    
    print("=" * 80)
    print("🧪 STAGED LLM TESTING - TIMING EACH STAGE")
    print("=" * 80)
    print()
    
    # Load config
    config = load_config()
    print(f"🤖 Model: {config.get('model')}")
    print(f"📡 Endpoint: {config.get('endpoint')}")
    print()
    
    total_start = time.time()
    
    # STAGE 1: Extract EXIF GPS data
    print("📍 STAGE 1: Extract GPS from EXIF")
    print("-" * 80)
    stage1_start = time.time()
    gps_data = extract_gps_from_exif(image_path)
    stage1_time = time.time() - stage1_start
    
    if gps_data.get('lat') and gps_data.get('lon'):
        print(f"   Latitude:  {gps_data['lat']}")
        print(f"   Longitude: {gps_data['lon']}")
        if gps_data.get('altitude'):
            print(f"   Altitude:  {gps_data['altitude']}m")
        if gps_data.get('heading'):
            print(f"   Heading:   {gps_data['heading']}° {gps_data.get('cardinal', '')}")
    else:
        print("   ⚠️  No GPS data found")
    print(f"   ⏱️  Time: {stage1_time:.2f}s")
    print()
    
    # STAGE 2: Get POI info (only if GPS available)
    location_data = {}
    nearby_pois = []
    
    if gps_data.get('lat') and gps_data.get('lon'):
        print("🌍 STAGE 2: Get POI info from Overpass API")
        print("-" * 80)
        stage2_start = time.time()
        
        # Geocode first
        print("   Geocoding location...")
        location_data = geocode_location(gps_data['lat'], gps_data['lon'])
        if location_data.get('city'):
            print(f"   City: {location_data['city']}, {location_data.get('country', 'N/A')}")
        
        # Search POIs
        print("   Searching nearby POIs...")
        nearby_pois = search_nearby_pois(gps_data['lat'], gps_data['lon'], radius_m=100)
        
        if nearby_pois:
            for poi in nearby_pois:
                if poi.get('context'):
                    print(f"     • {poi['name']} ({poi['category']})")
                    print(f"       {poi['context']}")
                else:
                    print(f"     • {poi['name']} ({poi['category']})")
        
        stage2_time = time.time() - stage2_start
        print(f"   ⏱️  Time: {stage2_time:.2f}s")
        print()
    
    # STAGE 3: Scale image for model
    print("📐 STAGE 3: Scale image for LLM vision model")
    print("-" * 80)
    stage3_start = time.time()
    base64_image, orig_w, orig_h, scaled_size, is_pano = scale_image_for_model(image_path)
    stage3_time = time.time() - stage3_start
    
    print(f"   Original: {orig_w}x{orig_h}")
    print(f"   Scaled: {scaled_size[0]}x{scaled_size[1]}")
    print(f"   Panorama: {is_pano}")
    print(f"   ⏱️  Time: {stage3_time:.2f}s")
    print()
    
    # STAGE 4: Analyze photo content (what's in the image)
    print("🔍 STAGE 4: Quick photo analysis (using llava:7b for speed)")
    print("-" * 80)
    stage4_start = time.time()
    photo_analysis = analyze_photo_content(base64_image, config)
    stage4_time = time.time() - stage4_start
    
    print(f"   Main subject: {photo_analysis.get('main_subject', 'N/A')}")
    print(f"   Scene type: {photo_analysis.get('scene_type', 'N/A')}")
    print(f"   Background: {photo_analysis.get('background', 'N/A')}")
    print(f"   ⏱️  Time: {stage4_time:.2f}s")
    print()
    
    # Brief pause to allow model to fully release resources
    print("   💤 Allowing model to reset (2s)...")
    time.sleep(2)
    
    # STAGE 5: Generate content using provided prompt template
    print(f"✍️  STAGE 5: Generate content (using {config.get('model')})")
    print(f"   Prompt file: {prompt_file}")
    print("-" * 80)
    stage5_start = time.time()
    
    # Read prompt template
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_template = f.read().strip()
    
    # Replace placeholders with actual data (same as original script + Stage 4 analysis)
    prompt_text = prompt_template.format(
        photo_gps_lat=gps_data.get('lat', 'N/A'),
        photo_gps_lon=gps_data.get('lon', 'N/A'),
        photo_altitude=gps_data.get('altitude', 'N/A'),
        photo_heading=gps_data.get('heading', 'N/A'),
        photo_cardinal=gps_data.get('cardinal', 'N/A'),
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
        ]) if nearby_pois else 'none',
        # Stage 4 photo analysis placeholders
        photo_main_subject=photo_analysis.get('main_subject', 'N/A'),
        photo_background=photo_analysis.get('background', 'N/A'),
        photo_scene_type=photo_analysis.get('scene_type', 'N/A'),
        photo_visual_elements=', '.join(photo_analysis.get('visual_elements', [])) if isinstance(photo_analysis.get('visual_elements'), list) else 'N/A'
    )
    
    # Replace [model] placeholder
    prompt_text = prompt_text.replace('[model]', config.get('model', 'unknown'))
    
    # Save Stage 5 prompt for debugging
    stage5_prompt_path = "/tmp/ollama_stage5_prompt.txt"
    with open(stage5_prompt_path, 'w', encoding='utf-8') as f:
        f.write(prompt_text)
    print(f"   💾 Saved Stage 5 prompt to: {stage5_prompt_path}")
    
    # Send to LLM
    endpoint = config.get('endpoint', 'http://localhost:11434')
    model = config.get('model', 'qwen3-vl:32b')
    
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
    
    try:
        # Use config timeout (300s) for Stage 5
        timeout = config.get('timeout', 300)
        print(f"   ⏱️  Using timeout: {timeout}s")
        response = requests.post(f"{endpoint}/api/generate", json=payload, timeout=timeout)
        if response.status_code == 200:
            result = response.json()
            final_description = result.get('response', '').strip()
            response.close()  # Explicitly close to free resources
        else:
            final_description = f"Error: HTTP {response.status_code}"
            response.close()
    except Exception as e:
        final_description = f"Error: {str(e)}"
    
    stage5_time = time.time() - stage5_start
    
    print("RESULT:")
    print("=" * 80)
    print(final_description)
    print("=" * 80)
    print(f"   ⏱️  Time: {stage5_time:.2f}s")
    print()
    
    # TIMING SUMMARY
    total_time = time.time() - total_start
    print("⏱️  TIMING SUMMARY")
    print("=" * 80)
    print(f"Stage 1 (EXIF GPS):         {stage1_time:6.2f}s ({stage1_time/total_time*100:5.1f}%)")
    if location_data:
        print(f"Stage 2 (POI Search):       {stage2_time:6.2f}s ({stage2_time/total_time*100:5.1f}%)")
    print(f"Stage 3 (Image Scaling):    {stage3_time:6.2f}s ({stage3_time/total_time*100:5.1f}%)")
    if stage4_time > 0:
        print(f"Stage 4 (Photo Analysis):   {stage4_time:6.2f}s ({stage4_time/total_time*100:5.1f}%)")
    print(f"Stage 5 (LLM Generation):   {stage5_time:6.2f}s ({stage5_time/total_time*100:5.1f}%)")
    print(f"{'-' * 80}")
    print(f"TOTAL:                      {total_time:6.2f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
