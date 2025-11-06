"""
Geolocation Metadata Extractor
Extracts GPS coordinates from EXIF and reverse geocodes to human-readable locations
"""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple
import requests
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

class GeoExtractor:
    def __init__(self, config: Dict):
        self.config = config
        self.geocoding_config = config.get('metadata_extraction', {}).get('geocoding', {})
        self.cache_enabled = self.geocoding_config.get('cache_enabled', True)
        self.cache_file = self.geocoding_config.get('cache_file', 'geocode_cache.json')
        self.rate_limit = self.geocoding_config.get('rate_limit_seconds', 1.0)
        self.user_agent = self.geocoding_config.get('user_agent', 'SkiCycleRun/1.0')
        self.last_request_time = 0
        self.cache = self._load_cache()
        
    def _load_cache(self) -> Dict:
        """Load geocoding cache from disk"""
        if not self.cache_enabled:
            return {}
        
        cache_path = Path(self.cache_file)
        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load cache: {e}")
        return {}
    
    def _save_cache(self):
        """Save geocoding cache to disk"""
        if not self.cache_enabled:
            return
        
        cache_path = Path(self.cache_file)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(cache_path, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}")
    
    def extract_gps_from_exif(self, image_path: str) -> Optional[Tuple[float, float]]:
        """Extract GPS coordinates from image EXIF data"""
        try:
            image = Image.open(image_path)
            exif_data = image._getexif()
            
            if not exif_data:
                return None
            
            # Find GPS info
            gps_info = {}
            for tag, value in exif_data.items():
                decoded = TAGS.get(tag, tag)
                if decoded == "GPSInfo":
                    for gps_tag in value:
                        sub_decoded = GPSTAGS.get(gps_tag, gps_tag)
                        gps_info[sub_decoded] = value[gps_tag]
            
            if not gps_info:
                return None
            
            # Extract latitude
            lat = self._convert_to_degrees(gps_info.get('GPSLatitude'))
            lat_ref = gps_info.get('GPSLatitudeRef')
            if lat and lat_ref and lat_ref == 'S':
                lat = -lat
            
            # Extract longitude
            lon = self._convert_to_degrees(gps_info.get('GPSLongitude'))
            lon_ref = gps_info.get('GPSLongitudeRef')
            if lon and lon_ref and lon_ref == 'W':
                lon = -lon
            
            if lat and lon:
                return (lat, lon)
            
        except Exception as e:
            print(f"Error extracting GPS from {image_path}: {e}")
        
        return None
    
    def _convert_to_degrees(self, value) -> Optional[float]:
        """Convert GPS coordinates to degrees"""
        if not value:
            return None
        
        try:
            d, m, s = value
            return float(d) + float(m) / 60.0 + float(s) / 3600.0
        except:
            return None
    
    def reverse_geocode(self, lat: float, lon: float) -> Optional[Dict]:
        """Convert coordinates to location using OpenStreetMap Nominatim"""
        # Check cache first
        cache_key = f"{lat:.6f},{lon:.6f}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        
        try:
            url = self.geocoding_config.get('api_url', 'https://nominatim.openstreetmap.org/reverse')
            params = {
                'lat': lat,
                'lon': lon,
                'format': 'json',
                'zoom': 14,  # City/town level
                'addressdetails': 1
            }
            headers = {
                'User-Agent': self.user_agent
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            self.last_request_time = time.time()
            
            if response.status_code == 200:
                data = response.json()
                address = data.get('address', {})
                
                location_info = {
                    'city': address.get('city') or address.get('town') or address.get('village'),
                    'state': address.get('state'),
                    'country': address.get('country'),
                    'country_code': address.get('country_code'),
                    'display_name': data.get('display_name'),
                    'lat': lat,
                    'lon': lon
                }
                
                # Cache the result
                self.cache[cache_key] = location_info
                self._save_cache()
                
                return location_info
            else:
                print(f"Geocoding API error: {response.status_code}")
                
        except Exception as e:
            print(f"Error reverse geocoding ({lat}, {lon}): {e}")
        
        return None
    
    def format_location(self, location_info: Optional[Dict]) -> str:
        """Format location info into a short, readable string"""
        if not location_info:
            return "Unknown Location"
        
        city = location_info.get('city')
        state = location_info.get('state')
        country = location_info.get('country')
        
        # Build location string: "City, State" or "City, Country"
        if city and state:
            return f"{city}, {state}"
        elif city and country:
            return f"{city}, {country}"
        elif state and country:
            return f"{state}, {country}"
        elif city:
            return city
        elif country:
            return country
        else:
            return "Unknown Location"
    
    def extract_metadata(self, image_path: str) -> Dict:
        """Extract all metadata from image"""
        metadata = {
            'file_path': str(image_path),
            'file_name': Path(image_path).name,
            'timestamp': datetime.now().isoformat(),
            'gps_coordinates': None,
            'location': None,
            'location_formatted': "Unknown Location"
        }
        
        # Extract GPS coordinates
        coords = self.extract_gps_from_exif(image_path)
        if coords:
            lat, lon = coords
            metadata['gps_coordinates'] = {'lat': lat, 'lon': lon}
            
            # Reverse geocode to get location
            location_info = self.reverse_geocode(lat, lon)
            if location_info:
                metadata['location'] = location_info
                metadata['location_formatted'] = self.format_location(location_info)
        
        return metadata
