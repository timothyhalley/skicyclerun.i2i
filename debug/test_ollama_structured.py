#!/usr/bin/env python3
"""
Structured LLM test - clean separation of concerns with JSON tracking
Usage: python debug/test_ollama_structured.py <image_path> <prompt_file.txt>
"""

import sys
import json
import base64
import requests
import time
import math
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from io import BytesIO
from datetime import datetime


def load_config():
    """Load pipeline config to get LLM settings"""
    config_path = Path(__file__).parent.parent / "config" / "pipeline_config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config['llm_image_analysis']


def save_debug_json(image_name: str, data: dict, output_dir: str = "logs"):
    """Save debug JSON for this image"""
    # Ensure logs directory exists
    output_path = Path(__file__).parent.parent / output_dir / f"{image_name}_debug.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return str(output_path)


def extract_gps_from_exif(image_path: str) -> dict:
    """Stage 1: Extract minimal GPS data from EXIF"""
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
            
            # Return minimal GPS data
            return {
                'latitude': lat,
                'longitude': lon,
                'heading': heading,
                'cardinal': cardinal
            }
            
    except Exception as e:
        print(f"⚠️  GPS extraction error: {e}")
        return {}


def geocode_location(lat: float, lon: float) -> dict:
    """Geocode GPS - get city from zoom 12, street from zoom 18"""
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        headers = {'User-Agent': 'SkiCycleRun-Debug/1.0'}
        
        # Call 1: Get city with zoom 12
        time.sleep(1.1)
        response = requests.get(url, params={
            'lat': lat, 'lon': lon, 'format': 'json',
            'zoom': 12, 'addressdetails': 1
        }, headers=headers, timeout=30)
        
        city = None
        state = None
        country = None
        
        if response.status_code == 200:
            address = response.json().get('address', {})
            city = (address.get('city') or address.get('town') or 
                   address.get('village') or address.get('suburb') or
                   address.get('hamlet') or address.get('municipality') or
                   address.get('county'))
            state = address.get('state') or address.get('region')
            country = address.get('country')
        
        # Call 2: Get street with zoom 18
        time.sleep(1.1)
        response = requests.get(url, params={
            'lat': lat, 'lon': lon, 'format': 'json',
            'zoom': 18, 'addressdetails': 1
        }, headers=headers, timeout=30)
        
        road = None
        house_number = None
        street_address = None
        
        if response.status_code == 200:
            address = response.json().get('address', {})
            road = address.get('road')
            house_number = address.get('house_number')
            if road:
                street_address = f"{house_number} {road}" if house_number else road
        
        return {
            'city': city,
            'state': state,
            'country': country,
            'street_address': street_address,
            'road': road,
            'house_number': house_number
        }
            
    except Exception as e:
        print(f"⚠️  Geocoding error: {e}")
        return {}


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two GPS coordinates using Haversine formula"""
    R = 6371000  # Earth radius in meters
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def search_nearby_pois(lat: float, lon: float, radius_m: int = 300) -> list:
    """Stage 2: POI search with distance calculation and sorting"""
    
    overpass_urls = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.openstreetmap.fr/api/interpreter"
    ]
    
    query = f"""
    [out:json][timeout:25];
    (
      nwr["tourism"](around:{radius_m},{lat},{lon});
      nwr["historic"](around:{radius_m},{lat},{lon});
      nwr["leisure"](around:{radius_m},{lat},{lon});
      nwr["natural"](around:{radius_m},{lat},{lon});
      nwr["waterway"](around:{radius_m},{lat},{lon});
      nwr["boundary"~"protected_area|national_park"](around:{radius_m},{lat},{lon});
      nwr["railway"~"station|subway_entrance|rail"](around:{radius_m},{lat},{lon});
      nwr["station"="subway"](around:{radius_m},{lat},{lon});
      nwr["public_transport"="station"](around:{radius_m},{lat},{lon});
      nwr["amenity"~"place_of_worship|theatre|arts_centre|library|restaurant|cafe|bar|pub|marketplace"](around:{radius_m},{lat},{lon});
      nwr["man_made"~"lighthouse|tower|windmill|bridge|monument|obelisk|clock"](around:{radius_m},{lat},{lon});
      nwr["building"~"church|temple|mosque|shrine|cathedral|castle|palace|fort|ruins"](around:{radius_m},{lat},{lon});
      nwr["route"~"hiking|bicycle"](around:{radius_m},{lat},{lon});
      nwr["shop"](around:{radius_m},{lat},{lon});
    );
    out tags center;
    """
    
    for overpass_url in overpass_urls:
        try:
            server_name = overpass_url.split('//')[1].split('/')[0]
            print(f"   🔄 Trying {server_name}")
            response = requests.post(overpass_url, data=query, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                elements = data.get('elements', [])
                
                pois = []
                seen_names = set()
                for elem in elements:
                    tags = elem.get('tags', {})
                    name = tags.get('name', 'Unnamed')
                    
                    if name == 'Unnamed' or name in seen_names:
                        continue
                    
                    seen_names.add(name)
                    
                    # Get POI coordinates
                    poi_lat = None
                    poi_lon = None
                    if elem.get('type') == 'node':
                        poi_lat = elem.get('lat')
                        poi_lon = elem.get('lon')
                    elif 'center' in elem:
                        poi_lat = elem['center'].get('lat')
                        poi_lon = elem['center'].get('lon')
                    
                    if poi_lat is None or poi_lon is None:
                        continue
                    
                    # Calculate distance
                    distance_m = calculate_distance(lat, lon, poi_lat, poi_lon)
                    
                    # Simple classification
                    if 'tourism' in tags:
                        classification = tags['tourism']
                    elif 'historic' in tags:
                        classification = tags['historic']
                    elif tags.get('amenity') == 'clock' or tags.get('man_made') == 'clock':
                        classification = 'clock'
                    else:
                        classification = 'landmark'
                    
                    pois.append({
                        'name': name,
                        'classification': classification,
                        'distance_m': round(distance_m, 1),
                        'wikipedia': tags.get('wikipedia'),
                        'wikidata': tags.get('wikidata')
                    })
                
                # Sort by distance (closest first) and limit to top 5
                pois.sort(key=lambda x: x['distance_m'])
                pois = pois[:5]
                
                print(f"   ✅ Found {len(pois)} unique POIs (sorted by distance)")
                return pois
                
            elif response.status_code == 504:
                print(f"   ⏳ Server timeout, trying next...")
                time.sleep(2)
                continue
                
        except Exception as e:
            print(f"   ⚠️  Error: {e}")
            continue
    
    print(f"   ❌ POI search failed")
    return []


def research_primary_poi(poi_name: str, poi_classification: str, city: str, country: str, lat: float, lon: float, config: dict) -> dict:
    """Stage 3: Research POI with GPS grounding - ignore OSM classification, discover actual type
    
    Uses GPS coordinates to help LLM ground the location accurately
    Returns: dict with 'poi_name', 'brief_context', 'error' if failed
    """
    
    prompt = f"""What is {poi_name} at GPS coordinates {lat:.4f}, {lon:.4f} in {city}, {country}?

What TYPE of place is this? (museum, gallery, shop, restaurant, attraction, monument, etc.)
What is it known for? What can visitors experience there?

Provide 2-3 sentences of FACTS only. Use the GPS location to identify it accurately."""
    
    endpoint = config.get('endpoint', 'http://localhost:11434')
    model = 'ministral-3:8b'  # Quick factual text generation
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,  # Slightly higher for better recall
            "num_predict": 250  # Match manual test output
        }
    }
    
    try:
        response = requests.post(f"{endpoint}/api/generate", json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            brief_context = result.get('response', '').strip()
            response.close()
            
            return {
                "poi_name": poi_name,
                "poi_classification": poi_classification,
                "brief_context": brief_context
            }
        else:
            response.close()
            return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def research_poi(poi_name: str, poi_classification: str, lat: float, lon: float, wikipedia_tag: str = None, wikidata_tag: str = None, country: str = None) -> str:
    """DEPRECATED - Wikipedia research function (kept for reference)
    
    Priority:
    1. Use wikipedia tag from OSM if available
    2. Use wikidata tag from OSM if available
    3. Fall back to geo-search with country-specific language
    """
    
    # Try direct Wikipedia link from OSM first
    if wikipedia_tag:
        try:
            # Format: "lang:Page_Title" or just "Page_Title"
            if ':' in wikipedia_tag:
                lang, title = wikipedia_tag.split(':', 1)
            else:
                lang = 'en'
                title = wikipedia_tag
            
            api_url = f"https://{lang}.wikipedia.org/w/api.php"
            extract_params = {
                "action": "query",
                "prop": "extracts",
                "titles": title,
                "exintro": True,
                "explaintext": True,
                "exsentences": 3,
                "format": "json"
            }
            
            response = requests.get(api_url, params=extract_params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                pages = data.get('query', {}).get('pages', {})
                if pages:
                    page_data = list(pages.values())[0]
                    extract = page_data.get('extract', '').strip()
                    if extract:
                        return extract
        except Exception as e:
            print(f"      ⚠️  Wikipedia tag lookup failed: {e}")
            pass
    
    # Try Wikidata lookup
    if wikidata_tag:
        try:
            # Get Wikipedia link from Wikidata
            wikidata_url = "https://www.wikidata.org/w/api.php"
            wikidata_params = {
                "action": "wbgetentities",
                "ids": wikidata_tag,
                "props": "sitelinks",
                "format": "json"
            }
            
            response = requests.get(wikidata_url, params=wikidata_params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                entity = data.get('entities', {}).get(wikidata_tag, {})
                sitelinks = entity.get('sitelinks', {})
                
                # Prefer English, but accept any language
                for site_key in ['enwiki', 'jawiki', 'eswiki', 'frwiki', 'dewiki', 'ptwiki']:
                    if site_key in sitelinks:
                        title = sitelinks[site_key].get('title')
                        lang = site_key.replace('wiki', '')
                        if title:
                            # Now get the extract
                            api_url = f"https://{lang}.wikipedia.org/w/api.php"
                            extract_params = {
                                "action": "query",
                                "prop": "extracts",
                                "titles": title,
                                "exintro": True,
                                "explaintext": True,
                                "exsentences": 3,
                                "format": "json"
                            }
                            
                            extract_response = requests.get(api_url, params=extract_params, timeout=10)
                            if extract_response.status_code == 200:
                                extract_data = extract_response.json()
                                pages = extract_data.get('query', {}).get('pages', {})
                                if pages:
                                    page_data = list(pages.values())[0]
                                    extract = page_data.get('extract', '').strip()
                                    if extract:
                                        return extract
        except Exception:
            pass
    
    # Language mapping for geo-search fallback
    country_to_lang = {
        'Japan': 'ja', '日本': 'ja',
        'Spain': 'es', 'España': 'es',
        'Portugal': 'pt',
        'France': 'fr', 'République française': 'fr',
        'Germany': 'de', 'Deutschland': 'de',
        'Italy': 'it', 'Italia': 'it',
        'China': 'zh', '中国': 'zh',
        'Mexico': 'es', 'México': 'es',
        'Argentina': 'es',
        'Colombia': 'es',
        'Costa Rica': 'es',
        'Panama': 'es', 'Panamá': 'es',
        'Guatemala': 'es',
        'Brazil': 'pt', 'Brasil': 'pt'
    }
    
    def try_wikipedia(lang: str, poi_name: str, lat: float, lon: float) -> str:
        """Try a specific Wikipedia language edition"""
        try:
            api_url = f"https://{lang}.wikipedia.org/w/api.php"
            
            # Step 1: Try direct title search first (exact match)
            title_params = {
                "action": "query",
                "prop": "extracts",
                "titles": poi_name,
                "exintro": True,
                "explaintext": True,
                "exsentences": 3,
                "format": "json",
                "redirects": 1
            }
            
            title_response = requests.get(api_url, params=title_params, timeout=10)
            if title_response.status_code == 200:
                title_data = title_response.json()
                pages = title_data.get('query', {}).get('pages', {})
                if pages:
                    page_data = list(pages.values())[0]
                    # Check if it's a real page (not missing)
                    if 'missing' not in page_data:
                        extract = page_data.get('extract', '').strip()
                        if extract:
                            return extract
            
            # Step 2: Geo-fenced search with larger radius
            geosearch_params = {
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{lat}|{lon}",
                "gsradius": 2000,  # Increased to 2km for linear features like railways
                "gslimit": 20,
                "format": "json"
            }
            
            geo_response = requests.get(api_url, params=geosearch_params, timeout=10)
            if geo_response.status_code != 200:
                return None
            
            geo_data = geo_response.json()
            articles = geo_data.get('query', {}).get('geosearch', [])
            
            if not articles:
                return None
            
            # Step 3: Find best match by name or use closest
            best_match = None
            poi_name_lower = poi_name.lower()
            
            for article in articles:
                article_title = article.get('title', '').lower()
                if poi_name_lower in article_title or article_title in poi_name_lower:
                    best_match = article
                    break
            
            if not best_match:
                best_match = articles[0]
            
            # Step 4: Get extract from matched article
            page_id = best_match.get('pageid')
            extract_params = {
                "action": "query",
                "prop": "extracts",
                "pageids": page_id,
                "exintro": True,
                "explaintext": True,
                "exsentences": 3,
                "format": "json"
            }
            
            extract_response = requests.get(api_url, params=extract_params, timeout=10)
            if extract_response.status_code != 200:
                return None
            
            extract_data = extract_response.json()
            pages = extract_data.get('query', {}).get('pages', {})
            
            if not pages:
                return None
            
            page_data = list(pages.values())[0]
            extract = page_data.get('extract', '').strip()
            
            return extract if extract else None
            
        except Exception:
            return None
    
    # Try country-specific language, then English
    if country:
        lang = country_to_lang.get(country, 'en')
        result = try_wikipedia(lang, poi_name, lat, lon)
        if result:
            return result
    
    # Always try English as fallback
    result = try_wikipedia('en', poi_name, lat, lon)
    if result:
        return result
    
    return "No historical context available"


def scale_image_for_model(image_path: str, max_dim: int = 1024) -> tuple:
    """Stage 4: Scale image for LLM"""
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        orig_width, orig_height = img.size
        aspect_ratio = orig_width / orig_height
        
        # Detect panorama
        is_panorama = aspect_ratio > 2.0 or aspect_ratio < 0.5
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


def analyze_primary_subject(base64_image: str, config: dict, pois: list = None) -> dict:
    """Stage 5: Analyze activity/context and determine photographer location"""
    
    # Determine closest POI (where photographer is likely AT)
    closest_poi = None
    if pois and len(pois) > 0:
        closest_poi = pois[0]  # Already sorted by distance
    
    prompt = """Describe what is in this photo. What activity or scene?

Is this INTERIOR (inside a building) or EXTERIOR (outdoors)?

Answer in JSON only:
{
  "activity": "brief description of scene",
  "scene_type": "urban/nature/historic/transit/beach/waterfront/mountain/other",
  "is_interior": true/false
}"""
    
    endpoint = config.get('endpoint', 'http://localhost:11434')
    model = 'llava:7b'
    
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [base64_image],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 100
        }
    }
    
    try:
        response = requests.post(f"{endpoint}/api/generate", json=payload, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            raw_response = result.get('response', '').strip()
            response.close()
            
            # Try to parse JSON
            try:
                if '```json' in raw_response:
                    json_str = raw_response.split('```json')[1].split('```')[0].strip()
                elif '```' in raw_response:
                    json_str = raw_response.split('```')[1].split('```')[0].strip()
                else:
                    json_str = raw_response
                
                parsed = json.loads(json_str)
                # Add closest POI info
                parsed['closest_poi'] = closest_poi
                return parsed
            except:
                return {
                    "activity": raw_response,
                    "scene_type": "unknown",
                    "is_interior": False,
                    "closest_poi": closest_poi
                }
        else:
            response.close()
            return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def generate_final_content(base64_image: str, metadata: dict, prompt_file: str, config: dict) -> str:
    """Stage 6: Generate final content with metadata injection"""
    
    # Read prompt template
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_template = f.read().strip()
    
    # Format POI list with research context - keep all 5 sorted by distance
    # IMPORTANT: Don't include OSM classification - let research define the type
    poi_text = ""
    if metadata.get('pois'):
        poi_lines = []
        for poi in metadata['pois']:
            research = poi.get('research', '')
            if research and research != 'No specific information available.':
                # Just name + research - no OSM classification to avoid confusion
                poi_lines.append(f"• {poi['name']}: {research}")
            else:
                poi_lines.append(f"• {poi['name']}")
        poi_text = '\n'.join(poi_lines)
    else:
        poi_text = "None found"
    
    # Determine watermark_line2 format based on country
    location = metadata.get('location', {})
    country = location.get('country', '')
    city = location.get('city', 'N/A')
    state = location.get('state', 'N/A')
    
    # Watermark line2 format per guide rules
    if country in ['United States', 'Canada']:
        watermark_line2_format = f"{city}, {state}, {country}"
    else:
        watermark_line2_format = f"{city}, {country}"
    
    # Replace placeholders (support both template styles)
    activity = metadata.get('primary_subject', {}).get('activity', 'N/A')
    scene_type = metadata.get('primary_subject', {}).get('scene_type', 'N/A')
    is_interior = metadata.get('primary_subject', {}).get('is_interior', False)
    closest_poi = metadata.get('primary_subject', {}).get('closest_poi')
    
    # Determine photographer location context
    # If interior + closest POI is a building < 30m away, assume you're inside it
    photographer_context = ""
    if closest_poi and is_interior:
        distance = closest_poi.get('distance_m', 999)
        poi_type = closest_poi.get('classification', '')
        building_types = ['hotel', 'museum', 'building', 'house', 'accommodation', 'tourism', 'historic']
        
        if distance < 30 and any(bt in poi_type for bt in building_types):
            photographer_context = f"Inside {closest_poi['name']}"
            # Remove this POI from the nearby list to avoid duplication
            poi_text_lines = poi_text.split('\n')
            poi_text = '\n'.join([line for line in poi_text_lines if closest_poi['name'] not in line])
    
    # Add POI research context from closest POI
    poi_context = ""
    if closest_poi and 'research' in closest_poi:
        poi_context = closest_poi['research']
    
    # Fix Interior/Exterior display - show proper text not boolean
    interior_exterior_text = "Interior photo" if is_interior else "Exterior photo"
    
    # GROUND ZERO: For urban scenes, street address is the primary reference
    street_address = location.get('street_address', '')
    street_research = location.get('street_research', '')
    ground_zero = ""
    if scene_type == 'urban' and street_address:
        if street_research:
            ground_zero = f"📍 GROUND ZERO: {street_address}, {city}\nAbout this street: {street_research}"
        else:
            ground_zero = f"📍 GROUND ZERO: {street_address}, {city}"
    
    prompt_text = prompt_template.format(
        photo_activity=activity,
        photo_scene_type=scene_type,
        photo_main_subject=activity,  # Backward compatibility
        photo_subject_type=scene_type,  # Backward compatibility
        photographer_context=photographer_context,
        is_interior_scene=is_interior,
        interior_exterior_text=interior_exterior_text,
        poi_context=poi_context,
        photo_city=city,
        photo_state=state,
        photo_state_or_province=state,
        photo_country=country,
        photo_gps_lat=metadata.get('gps', {}).get('latitude', 'N/A'),
        photo_gps_lon=metadata.get('gps', {}).get('longitude', 'N/A'),
        photo_heading=metadata.get('gps', {}).get('heading', 'N/A'),
        photo_cardinal=metadata.get('gps', {}).get('cardinal', 'N/A'),
        nearby_pois=poi_text,
        watermark_line2_format=watermark_line2_format,
        ground_zero=ground_zero,
        street_address=street_address
    )
    
    # Save prompt for debugging
    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = logs_dir / f"{metadata['image_name']}_prompt.txt"
    with open(prompt_path, 'w', encoding='utf-8') as f:
        f.write(prompt_text)
    print(f"   💾 Saved prompt to: {prompt_path}")
    
    # Send to LLM - use text-only model since no image in Stage 6
    endpoint = config.get('endpoint', 'http://localhost:11434')
    model = 'mixtral:8x7b'  # Proven long-context prose generation
    timeout = config.get('timeout', 300)
    
    # Stage 6 uses text-only - image already analyzed in Stage 5
    payload = {
        "model": model,
        "prompt": prompt_text,
        "stream": False,
        "options": {
            "temperature": 0.5,        # Balanced for descriptive content
            "top_p": 0.9,              # Standard for good generation
            "num_predict": 400         # Enough for complete paragraphs
        }
    }
    
    # Save detailed request info for debugging
    request_info = {
        "endpoint": endpoint,
        "model": model,
        "timeout": timeout,
        "prompt": prompt_text,
        "prompt_length_chars": len(prompt_text),
        "prompt_length_lines": len(prompt_text.split('\n')),
        "text_only": True,
        "options": payload["options"]
    }
    request_info_path = logs_dir / f"{metadata['image_name']}_request.json"
    with open(request_info_path, 'w', encoding='utf-8') as f:
        json.dump(request_info, f, indent=2, ensure_ascii=False)
    print(f"   💾 Saved request details to: {request_info_path}")
    
    print(f"   📤 Sending to LLM (TEXT ONLY - no image):")
    print(f"      Model: {model}")
    print(f"      Endpoint: {endpoint}")
    print(f"      Prompt: {len(prompt_text)} chars, {len(prompt_text.split(chr(10)))} lines")
    print(f"      Temperature: {payload['options']['temperature']}")
    print(f"      Top P: {payload['options']['top_p']}")
    print(f"      Timeout: {timeout}s")
    
    try:
        import threading
        import sys
        
        # Progress tracking
        start_time = time.time()
        response_received = threading.Event()
        response_data = {}
        
        def make_request():
            """Make the request in a separate thread"""
            try:
                resp = requests.post(f"{endpoint}/api/generate", json=payload, timeout=timeout)
                response_data['response'] = resp
                response_data['status'] = resp.status_code
            except Exception as e:
                response_data['error'] = e
            finally:
                response_received.set()
        
        # Start request in background
        request_thread = threading.Thread(target=make_request)
        request_thread.daemon = True
        request_thread.start()
        
        # Show progress bar while waiting
        print("   ", end="", flush=True)
        while not response_received.is_set():
            elapsed = time.time() - start_time
            progress = min(elapsed / timeout, 1.0)
            bar_length = 50
            filled = int(bar_length * progress)
            bar = '█' * filled + '░' * (bar_length - filled)
            
            sys.stdout.write(f"\r   [{bar}] {elapsed:.1f}s / {timeout}s")
            sys.stdout.flush()
            
            if response_received.wait(0.5):
                break
        
        # Clear progress bar and show final time
        elapsed = time.time() - start_time
        sys.stdout.write(f"\r   {'✓ Completed' if elapsed < timeout else '⏱ Timeout'}: {elapsed:.1f}s                    \n")
        sys.stdout.flush()
        
        # Check for errors
        if 'error' in response_data:
            raise response_data['error']
        
        response = response_data.get('response')
        if response and response.status_code == 200:
            result = response.json()
            content = result.get('response', '').strip()
            response.close()
            
            # Debug: check if response is empty
            if not content:
                print("   ⚠️  LLM returned empty response!")
                return {'error': 'Empty response from LLM'}
            
            # Parse simple format response (just DESCRIPTION, no SUMMARY)
            try:
                # Extract WATERMARK line if present
                watermark_line1 = None
                if 'WATERMARK:' in content and 'DESCRIPTION:' in content:
                    watermark_section = content.split('WATERMARK:')[1].split('DESCRIPTION:')[0].strip()
                    watermark_line1 = watermark_section.strip()
                
                # Content after "DESCRIPTION:" is the description
                if 'DESCRIPTION:' in content:
                    description = content.split('DESCRIPTION:')[1].strip()
                else:
                    description = content.strip()
                
                # If no explicit watermark, fall back to first sentence
                if not watermark_line1:
                    sentences = description.split('.')
                    watermark_line1 = sentences[0].strip() + '.' if sentences else description[:100]
                
                # Get location format from metadata
                location = metadata.get('location', {})
                watermark_line2 = f"{location.get('city', 'Unknown')}, {location.get('country', 'Unknown')}"
                
                # Return parsed fields
                return {
                    'raw_response': content,
                    'description': description,
                    'summary': watermark_line1,  # Watermark or first sentence
                    'watermark_line1': watermark_line1,
                    'watermark_line2': watermark_line2
                }
            except Exception as parse_error:
                # If parsing fails, return raw content with error
                print(f"   ⚠️  Parse error: {parse_error}")
                print(f"   📄 Raw response (first 200 chars): {content[:200]}")
                return {'raw_response': content, 'parse_error': str(parse_error)}
        else:
            response.close()
            return {'error': f"HTTP {response.status_code}"}
    except Exception as e:
        return {'error': str(e)}


def main():
    if len(sys.argv) != 3:
        print("Usage: python debug/test_ollama_structured.py <image_path> <prompt_file.txt>")
        print("\nExample:")
        print("  python debug/test_ollama_structured.py pipeline/albums/photo.jpg debug/llm_prompt_simple.txt")
        sys.exit(1)
    
    image_path = sys.argv[1]
    prompt_file = sys.argv[2]
    
    if not Path(image_path).exists():
        print(f"❌ Image not found: {image_path}")
        sys.exit(1)
    
    if not Path(prompt_file).exists():
        print(f"❌ Prompt file not found: {prompt_file}")
        sys.exit(1)
    
    # Get image name for JSON file
    image_name = Path(image_path).stem
    
    # Initialize metadata structure
    metadata = {
        'image_name': image_name,
        'timestamp': datetime.now().isoformat(),
        'gps': {},
        'location': {},
        'pois': [],
        'image_info': {},
        'primary_subject': {},
        'final_content': '',
        'timing': {}
    }
    
    print("=" * 80)
    print("🧪 STRUCTURED LLM TESTING WITH JSON TRACKING")
    print("=" * 80)
    print()
    
    # Load config
    config = load_config()
    print(f"🤖 Main Model: {config.get('model')}")
    print(f"📡 Endpoint: {config.get('endpoint')}")
    print()
    
    total_start = time.time()
    
    # STAGE 1: Extract GPS
    print("📍 STAGE 1: Extract GPS from EXIF")
    print("-" * 80)
    stage1_start = time.time()
    gps_data = extract_gps_from_exif(image_path)
    stage1_time = time.time() - stage1_start
    metadata['gps'] = gps_data
    metadata['timing']['stage1_gps'] = stage1_time
    
    if gps_data.get('latitude') and gps_data.get('longitude'):
        print(f"   Latitude:  {gps_data['latitude']}")
        print(f"   Longitude: {gps_data['longitude']}")
        if gps_data.get('heading'):
            print(f"   Heading:   {gps_data['heading']}° {gps_data.get('cardinal', '')}")
    else:
        print("   ⚠️  No GPS data found")
    print(f"   ⏱️  Time: {stage1_time:.2f}s")
    print()
    
    # Get location for POI research
    location_data = {}
    if gps_data.get('latitude') and gps_data.get('longitude'):
        print("🌍 Geocoding location...")
        location_data = geocode_location(gps_data['latitude'], gps_data['longitude'])
        
        # Display full geocoding result
        geocoded_city = location_data.get('city', 'Unknown')
        city = location_data.get('city', 'Unknown')
        country = location_data.get('country', 'Unknown')
        street_address = location_data.get('street_address', 'N/A')
        
        print(f"   📍 Location: {city}, {country}")
        print(f"   📍 Street: {street_address}")
        print()
    
    # STAGE 2: POI Search
    if gps_data.get('latitude') and gps_data.get('longitude'):
        print("🔍 STAGE 2: Search nearby POIs")
        print("-" * 80)
        stage2_start = time.time()
        pois = search_nearby_pois(gps_data['latitude'], gps_data['longitude'], radius_m=300)
        stage2_time = time.time() - stage2_start
        metadata['pois'] = pois
        metadata['timing']['stage2_poi_search'] = stage2_time
        
        if pois:
            for poi in pois:
                distance_m = poi.get('distance_m', 0)
                print(f"   • {poi['name']} ({poi['classification']}) - {distance_m}m")
        
        print(f"   ⏱️  Time: {stage2_time:.2f}s")
        print()
        
        # Save location data to metadata
        metadata['location'] = location_data
        
        # Serialize after Stage 2
        debug_path = Path(__file__).parent.parent / "logs" / f"{metadata['image_name']}_debug.json"
        with open(debug_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # STAGE 3: Research ALL POIs + Street Address (if urban)
        print("📚 STAGE 3: Research POIs and Location")
        print("-" * 80)
        stage3_start = time.time()
        
        # For urban scenes, research the street itself as Ground Zero POI
        street_address = location_data.get('street_address')
        road = location_data.get('road')
        if street_address and road:
            print(f"   🎯 Researching GROUND ZERO: {road}")
            
            # Special prompt for streets to capture nicknames and cultural significance
            street_prompt = f"""State ONLY factual information about {road} in {location_data.get('city', 'Unknown')}, {location_data.get('country', 'Unknown')}.

Does this street have a popular nickname or is it known by another name? (e.g., Pink Street, The Golden Mile, etc.)
What is this street famous for? (nightlife, shopping, historic architecture, etc.)

Provide 2-3 sentences of FACTS only about this street's significance and what it's known for. Do NOT suggest checking websites. Just state what you know."""
            
            # Use direct API call instead of research_primary_poi to use custom prompt
            endpoint = config.get('endpoint', 'http://localhost:11434')
            model = 'ministral-3:8b'
            payload = {
                "model": model,
                "prompt": street_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 250
                }
            }
            
            try:
                response = requests.post(f"{endpoint}/api/generate", json=payload, timeout=30)
                if response.status_code == 200:
                    result = response.json()
                    brief_context = result.get('response', '').strip()
                    response.close()
                    street_research = {"brief_context": brief_context}
                else:
                    response.close()
                    street_research = {"error": "failed"}
            except Exception as e:
                street_research = {"error": str(e)}
            
            # Add street research to location data
            if 'error' not in street_research:
                location_data['street_research'] = street_research.get('brief_context', '')
                metadata['location'] = location_data
                print(f"   ✓ Street context added")
            else:
                location_data['street_research'] = None
                metadata['location'] = location_data
        
        # Research each POI
        if pois:
            for poi in pois:
                print(f"   Researching: {poi['name']} ({poi['classification']})")
                
                poi_research = research_primary_poi(
                    poi['name'],
                    poi['classification'],
                    location_data.get('city', 'Unknown'),
                    location_data.get('country', 'Unknown'),
                    gps_data['latitude'],
                    gps_data['longitude'],
                    config
                )
                
                # Merge research into existing POI object
                if 'error' not in poi_research:
                    poi['research'] = poi_research.get('brief_context', 'No information available.')
                else:
                    poi['research'] = 'No specific information available.'
        
        stage3_time = time.time() - stage3_start
        metadata['timing']['stage3_poi_research'] = stage3_time
        
        print(f"   ✓ Researched {len(pois) if pois else 0} POIs + street context")
        print(f"   ⏱️  Time: {stage3_time:.2f}s")
        print()
        
        # Serialize after Stage 3
        debug_path = Path(__file__).parent.parent / "logs" / f"{metadata['image_name']}_debug.json"
        with open(debug_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    # STAGE 4: Scale image
    print("📐 STAGE 4: Scale image for LLM")
    print("-" * 80)
    stage4_start = time.time()
    base64_image, orig_w, orig_h, scaled_size, is_pano = scale_image_for_model(image_path)
    stage4_time = time.time() - stage4_start
    metadata['image_info'] = {
        'original_size': f"{orig_w}x{orig_h}",
        'scaled_size': f"{scaled_size[0]}x{scaled_size[1]}",
        'is_panorama': is_pano
    }
    metadata['timing']['stage4_scaling'] = stage4_time
    
    print(f"   Original: {orig_w}x{orig_h}")
    print(f"   Scaled: {scaled_size[0]}x{scaled_size[1]}")
    print(f"   ⏱️  Time: {stage4_time:.2f}s")
    print()
    
    # Serialize after Stage 4
    debug_path = Path(__file__).parent.parent / "logs" / f"{metadata['image_name']}_debug.json"
    with open(debug_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    # STAGE 5: Analyze primary subject and location context
    print("👁️  STAGE 5: Analyze activity & photographer location")
    print("-" * 80)
    stage5_start = time.time()
    primary_subject = analyze_primary_subject(base64_image, config, metadata.get('pois', []))
    stage5_time = time.time() - stage5_start
    metadata['primary_subject'] = primary_subject
    metadata['timing']['stage5_subject_analysis'] = stage5_time
    
    print(f"   Activity: {primary_subject.get('activity', 'N/A')}")
    print(f"   Scene type: {primary_subject.get('scene_type', 'N/A')}")
    print(f"   Interior: {primary_subject.get('is_interior', False)}")
    
    closest = primary_subject.get('closest_poi')
    if closest:
        print(f"   📍 Photographer at: {closest['name']} ({closest.get('distance_m', 0)}m)")
    else:
        print(f"   📍 Photographer at: Unknown location")
    
    print(f"   ⏱️  Time: {stage5_time:.2f}s")
    print()
    
    # Serialize after Stage 5
    debug_path = Path(__file__).parent.parent / "logs" / f"{metadata['image_name']}_debug.json"
    with open(debug_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    # Brief pause before final generation
    print("   💤 Allowing model to reset (2s)...")
    time.sleep(2)
    
    # STAGE 6: Generate final content
    print("✍️  STAGE 6: Generate final travel content")
    print(f"   Model: {config.get('model')}")
    print("-" * 80)
    stage6_start = time.time()
    final_content = generate_final_content(base64_image, metadata, prompt_file, config)
    stage6_time = time.time() - stage6_start
    metadata['final_content'] = final_content
    metadata['timing']['stage6_generation'] = stage6_time
    
    print()
    print("📝 FINAL CONTENT:")
    print("=" * 80)
    
    # Display parsed fields if available
    if isinstance(final_content, dict):
        if 'error' in final_content:
            print(f"❌ ERROR: {final_content['error']}")
        else:
            if 'description' in final_content:
                print(f"📖 Description:\n{final_content['description']}\n")
            if 'summary' in final_content:
                print(f"📌 Summary:\n{final_content['summary']}\n")
            if 'watermark_line1' in final_content:
                print(f"🏷️  Watermark Line 1: {final_content['watermark_line1']}")
            if 'watermark_line2' in final_content:
                print(f"🏷️  Watermark Line 2: {final_content['watermark_line2']}")
            
            # Show error if present
            if 'error' in final_content:
                print(f"❌ Error: {final_content['error']}")
            
            # Show parse error if present
            if 'parse_error' in final_content:
                print(f"⚠️  Parse Error: {final_content['parse_error']}")
            
            # Also show raw if present and no parsed content
            if 'raw_response' in final_content and not any(k in final_content for k in ['description', 'summary']):
                print(f"📄 Raw Response:\n{final_content['raw_response']}")
    else:
        print(final_content)
    
    print("=" * 80)
    print(f"   ⏱️  Time: {stage6_time:.2f}s")
    print()
    
    # Save debug JSON
    total_time = time.time() - total_start
    metadata['timing']['total'] = total_time
    
    json_path = save_debug_json(image_name, metadata)
    print(f"💾 Saved debug JSON to: {json_path}")
    print()
    
    # TIMING SUMMARY
    print("⏱️  TIMING SUMMARY")
    print("=" * 80)
    print(f"Stage 1 (EXIF GPS):         {metadata['timing']['stage1_gps']:6.2f}s")
    if metadata.get('pois'):
        print(f"Stage 2 (POI Search):       {metadata['timing']['stage2_poi_search']:6.2f}s")
    print(f"Stage 4 (Image Scaling):    {metadata['timing']['stage4_scaling']:6.2f}s")
    print(f"Stage 5 (Subject Analysis): {metadata['timing']['stage5_subject_analysis']:6.2f}s")
    print(f"Stage 6 (Final Content):    {metadata['timing']['stage6_generation']:6.2f}s")
    print(f"{'-' * 80}")
    print(f"TOTAL:                      {total_time:6.2f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
