"""
Geolocation Metadata Extractor
Extracts GPS coordinates from EXIF and reverse geocodes to human-readable locations
"""
import json
import time
from datetime import datetime
from utils.time_utils import utc_now_iso_z, infer_utc_from_local_naive
from pathlib import Path
from typing import Optional, Dict, Tuple, List
import requests
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

class GeoExtractor:
    def __init__(self, config: Dict):
        self.config = config
        self.geocoding_config = config.get('metadata_extraction', {}).get('geocoding', {})
        self.cache_enabled = self.geocoding_config.get('cache_enabled', True)
        self.cache_file = self.geocoding_config.get('cache_file', 'geocode_cache.json')
        self.cache_only = self.geocoding_config.get('cache_only', False)
        self.rate_limit = self.geocoding_config.get('rate_limit_seconds', 1.0)
        self.user_agent = self.geocoding_config.get('user_agent', 'SkiCycleRun/1.0')
        self.last_request_time = 0
        self.cache = self._load_cache()
        # POI enrichment settings (Overpass)
        poi_cfg = config.get('metadata_extraction', {}).get('poi_enrichment', {})
        self.poi_enabled = poi_cfg.get('enabled', False)
        self.poi_radius_m = int(poi_cfg.get('radius_m', 500))
        self.poi_max_results = int(poi_cfg.get('max_results', 5))
        self.poi_timeout_s = int(poi_cfg.get('timeout_seconds', 15))
        self.overpass_url = poi_cfg.get('overpass_url', 'https://overpass-api.de/api/interpreter')
        self.poi_allowed_categories: List[str] = [
            c.lower() for c in poi_cfg.get('categories', [
                'museum','attraction','viewpoint','historic','natural'
            ])
        ]
        self.poi_use_heading = bool(poi_cfg.get('use_heading_filter', True))
        self.poi_fov_deg = float(poi_cfg.get('fov_degrees', 60))  # visible cone centered on heading
        self.poi_max_distance_m = int(poi_cfg.get('max_distance_m', self.poi_radius_m))
        self.poi_heading_weight = float(poi_cfg.get('heading_weight', 0.7))
        self.poi_distance_weight = float(poi_cfg.get('distance_weight', 0.3))
        
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

    def _convert_rational(self, value) -> Optional[float]:
        """Convert EXIF rational or tuple to float degrees (e.g., GPSImgDirection)."""
        if value is None:
            return None
        try:
            if isinstance(value, tuple) and len(value) == 2:
                num, den = value
                den = den or 1
                return float(num) / float(den)
            return float(value)
        except Exception:
            return None

    def _degrees_to_compass(self, deg: Optional[float]) -> Optional[str]:
        if deg is None:
            return None
        dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
        idx = int((deg % 360) / 22.5 + 0.5) % 16
        return dirs[idx]
    
    def reverse_geocode(self, lat: float, lon: float) -> Optional[Dict]:
        """Convert coordinates to location using OpenStreetMap Nominatim"""
        # Check cache first
        cache_key = f"{lat:.6f},{lon:.6f}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Dev mode: cache-only short circuit
        if self.cache_only:
            return None
        
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        
        try:
            url = self.geocoding_config.get('api_url', 'https://nominatim.openstreetmap.org/reverse')
            params = {
                'lat': lat,
                'lon': lon,
                'format': 'jsonv2',
                'zoom': int(self.geocoding_config.get('zoom', 14)),
                'addressdetails': 1,
                'namedetails': 1,
                'extratags': 1
            }
            headers = {
                'User-Agent': self.user_agent
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            self.last_request_time = time.time()
            
            if response.status_code == 200:
                data = response.json()
                address = data.get('address', {})
                namedetails = data.get('namedetails') or {}
                extratags = data.get('extratags') or {}
                location_info = {
                    'city': address.get('city') or address.get('town') or address.get('village') or address.get('hamlet') or address.get('suburb'),
                    'state': address.get('state'),
                    'country': address.get('country'),
                    'country_code': address.get('country_code'),
                    'display_name': data.get('display_name'),
                    'lat': lat,
                    'lon': lon,
                    'osm_type': data.get('osm_type'),
                    'osm_id': data.get('osm_id'),
                    'category': data.get('category'),
                    'type': data.get('type'),
                    'namedetails': namedetails,
                    'extratags': {k: extratags.get(k) for k in ['wikidata','wikipedia','brand','operator'] if k in extratags}
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

    def fetch_pois(self, lat: float, lon: float, heading_deg: Optional[float] = None) -> List[Dict]:
        """Query Overpass API for notable nearby POIs and return a ranked list.

        Filters include tourism (attraction, museum, viewpoint), historic, and natural features with names.
        """
        if not self.poi_enabled:
            return []
        # Build Overpass QL query
        radius = self.poi_radius_m
        query = f"""
[out:json][timeout:{self.poi_timeout_s}];
(
  node(around:{radius},{lat},{lon})["tourism"~"^(attraction|museum|viewpoint)$"]["name"]; 
  node(around:{radius},{lat},{lon})["historic"]["name"]; 
  node(around:{radius},{lat},{lon})["natural"]["name"]; 
);
out body {self.poi_max_results};
"""
        try:
            r = requests.post(self.overpass_url, data={'data': query}, headers={'User-Agent': self.user_agent}, timeout=self.poi_timeout_s)
            if r.status_code != 200:
                return []
            out = r.json()
            elements = out.get('elements', [])
            raw: List[Dict] = []
            for el in elements:
                tags = el.get('tags', {})
                name = tags.get('name')
                if not name:
                    continue
                plat = el.get('lat')
                plon = el.get('lon')
                # Compute rough distance and bearing
                d, b = self._distance_and_bearing(lat, lon, plat, plon)
                cat = tags.get('tourism') or ('historic' if 'historic' in tags else tags.get('natural'))
                if cat:
                    cat = str(cat).lower()
                raw.append({
                    'name': name,
                    'category': cat,
                    'distance_m': int(d),
                    'bearing_deg': round(b, 1),
                    'bearing_cardinal': self._degrees_to_compass(b),
                    'wikidata': tags.get('wikidata')
                })
            # Relevance filtering: category allowlist, distance cap, heading cone
            filtered: List[Dict] = []
            for it in raw:
                if it['category'] and self.poi_allowed_categories and it['category'] not in self.poi_allowed_categories:
                    continue
                if self.poi_max_distance_m and it['distance_m'] > self.poi_max_distance_m:
                    continue
                # Heading relevance
                if self.poi_use_heading and heading_deg is not None:
                    # angle difference in shortest arc
                    diff = abs(((it['bearing_deg'] - heading_deg + 180) % 360) - 180)
                    if diff > max(1.0, self.poi_fov_deg / 2.0):
                        continue
                    it['_heading_diff'] = diff
                else:
                    it['_heading_diff'] = None
                filtered.append(it)

            # Score and sort
            scored: List[Tuple[float, Dict]] = []
            for it in filtered:
                # distance score (closer is better)
                dist_score = max(0.0, 1.0 - (it['distance_m'] / float(self.poi_max_distance_m or self.poi_radius_m or 1)))
                # heading score (smaller diff is better)
                if it['_heading_diff'] is None:
                    head_score = 0.5  # neutral if no heading filter
                else:
                    head_score = max(0.0, 1.0 - (it['_heading_diff'] / max(1.0, self.poi_fov_deg / 2.0)))
                score = self.poi_heading_weight * head_score + self.poi_distance_weight * dist_score
                it['score'] = round(score, 3)
                scored.append((score, it))

            scored.sort(key=lambda x: x[0], reverse=True)
            top = [it for _, it in scored[: self.poi_max_results]]
            # Remove internal key
            for it in top:
                it.pop('_heading_diff', None)
            return top
        except Exception:
            return []

    def _distance_and_bearing(self, lat1: float, lon1: float, lat2: float, lon2: float) -> Tuple[float, float]:
        """Return distance in meters and initial bearing degrees from point1 to point2."""
        import math
        R = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        d = R * c
        y = math.sin(dlambda) * math.cos(phi2)
        x = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlambda)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        return d, brng
    
    # State/Province abbreviations for North America
    STATE_ABBREVIATIONS = {
        # US States
        'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA',
        'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA',
        'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA',
        'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
        'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS', 'Missouri': 'MO',
        'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ',
        'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH',
        'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
        'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT',
        'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY',
        'District of Columbia': 'DC',
        # Canadian Provinces/Territories
        'Alberta': 'AB', 'British Columbia': 'BC', 'Manitoba': 'MB', 'New Brunswick': 'NB',
        'Newfoundland and Labrador': 'NL', 'Northwest Territories': 'NT', 'Nova Scotia': 'NS',
        'Nunavut': 'NU', 'Ontario': 'ON', 'Prince Edward Island': 'PE', 'Quebec': 'QC',
        'Saskatchewan': 'SK', 'Yukon': 'YT'
    }

    def format_location(self, location_info: Optional[Dict]) -> str:
        """Format location info into a short, readable string
        
        Rules:
        - North America (USA/Canada): Use state/province abbreviations, omit country
          Example: "Denver, CO" not "Denver, Colorado, United States"
        - Other countries: Include full location with country
          Example: "Tokyo, Japan"
        """
        if not location_info:
            return "Unknown Location"
        
        city = location_info.get('city')
        state = location_info.get('state')
        country = location_info.get('country')
        country_code = location_info.get('country_code', '').upper()
        
        # Check if this is North America (USA or Canada)
        is_north_america = country_code in ['US', 'CA']
        
        if is_north_america:
            # North America: Use abbreviations, omit country
            if city and state:
                # Abbreviate state/province if possible
                state_abbrev = self.STATE_ABBREVIATIONS.get(state, state)
                return f"{city}, {state_abbrev}"
            elif city:
                return city
            elif state:
                state_abbrev = self.STATE_ABBREVIATIONS.get(state, state)
                return state_abbrev
            else:
                return "Unknown Location"
        else:
            # Other countries: Include country name
            if city and country:
                return f"{city}, {country}"
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
            'timestamp': utc_now_iso_z(),
            'date_taken': None,
            'date_taken_utc': None,
            'gps_coordinates': None,
            'location': None,
            'location_formatted': "Unknown Location",
            'heading': None
        }
        
        # Extract date taken and GPS from EXIF
        try:
            image = Image.open(image_path)
            exif_data = image._getexif()
            
            if exif_data:
                # Extract DateTimeOriginal (when photo was taken)
                for tag, value in exif_data.items():
                    decoded = TAGS.get(tag, tag)
                    if decoded == "DateTimeOriginal":
                        try:
                            # Format: "2023:01:15 14:30:45"
                            dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                            metadata['date_taken'] = dt.isoformat()
                        except:
                            pass
                        break
        except Exception as e:
            print(f"Warning: Could not extract EXIF date from {image_path}: {e}")
        
        # Extract GPS coordinates
        coords = self.extract_gps_from_exif(image_path)
        if coords:
            lat, lon = coords
            metadata['gps_coordinates'] = {'lat': lat, 'lon': lon}
            # Extract heading/bearing first (for POI relevance)
            heading_info = None
            try:
                image = Image.open(image_path)
                exif_data = image._getexif()
                if exif_data:
                    gps_info = {}
                    for tag, value in exif_data.items():
                        decoded = TAGS.get(tag, tag)
                        if decoded == "GPSInfo":
                            for gps_tag in value:
                                sub_decoded = GPSTAGS.get(gps_tag, gps_tag)
                                gps_info[sub_decoded] = value[gps_tag]
                    if gps_info:
                        heading = self._convert_rational(gps_info.get('GPSImgDirection'))
                        if heading is not None:
                            heading_info = {
                                'degrees': heading,
                                'cardinal': self._degrees_to_compass(heading),
                                'ref': gps_info.get('GPSImgDirectionRef')
                            }
            except Exception:
                heading_info = None

            # If we have a local date and GPS, infer UTC capture time
            if metadata.get('date_taken'):
                inferred = infer_utc_from_local_naive(metadata['date_taken'], lat, lon)
                if inferred:
                    metadata['date_taken_utc'] = inferred

            # Reverse geocode to get location
            location_info = self.reverse_geocode(lat, lon)
            if location_info:
                metadata['location'] = location_info
                metadata['location_formatted'] = self.format_location(location_info)
                # Optional POI enrichment (respect heading for relevance)
                pois = self.fetch_pois(lat, lon, heading_deg=(heading_info or {}).get('degrees'))
                if pois:
                    metadata['landmarks'] = pois
            # Persist heading info if we found it
            if heading_info:
                metadata['heading'] = heading_info
        
        return metadata
