"""
Geolocation Metadata Extractor
Extracts GPS coordinates from EXIF and reverse geocodes to human-readable locations
"""
import json
import os
import time
from datetime import datetime
from utils.time_utils import utc_now_iso_z, infer_utc_from_local_naive
from pathlib import Path
from typing import Optional, Dict, Tuple, List
import requests
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from .poi_osm_queries import get_nearby_interesting_pois, get_natural_context_pois, _merge_poi_lists

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
        # POI enrichment config.
        # POIs are cached in geocode_cache.json and intentionally NOT written to master.json.
        poi_cfg = config.get('metadata_extraction', {}).get('poi_enrichment', {})
        self.poi_enabled = poi_cfg.get('enabled', False)
        self.poi_radius_m = int(poi_cfg.get('radius_m', 50))
        progressive = poi_cfg.get('progressive_radii_m', [self.poi_radius_m, 120, 250])
        self.poi_progressive_radii: List[int] = sorted({max(10, int(r)) for r in progressive if r})
        if not self.poi_progressive_radii:
            self.poi_progressive_radii = [self.poi_radius_m]
        self.poi_max_results = int(poi_cfg.get('max_results', 5))
        self.poi_timeout_s = int(poi_cfg.get('timeout_seconds', 15))
        self.places_api_url = poi_cfg.get('places_api_url', 'https://maps.googleapis.com/maps/api/place/nearbysearch/json')
        self.poi_request_delay_s = float(poi_cfg.get('request_delay_seconds', 2.0))
        self.poi_rate_limit_backoff_s = int(poi_cfg.get('rate_limit_backoff_seconds', 60))
        self.last_poi_request_time = 0.0
        self.poi_backoff_until = 0.0
        self.last_poi_fetch_status = 'not_attempted'
        configured_categories = [c.lower() for c in poi_cfg.get('categories', []) if c]
        # If categories is empty, use a default "worthy" allow-list.
        self.poi_allowed_categories: List[str] = configured_categories or [
            'lodging',
            'restaurant', 'cafe', 'pub', 'marketplace',
            'park', 'trailhead', 'beach',
            'mountain', 'peak', 'volcano', 'ridge', 'hill', 'natural', 'waterfall',
            'historic', 'memorial', 'monument', 'castle', 'ruins', 'archaeological_site',
            'museum', 'gallery', 'attraction', 'viewpoint', 'national_park', 'protected_area',
            'lighthouse', 'bridge'
        ]
        # Map configured categories to equivalent Google type values.
        # This avoids false negatives when config uses broader labels
        # (e.g. "attraction") but Google returns "tourist_attraction".
        self.poi_category_aliases = {
            'lodging': {'hotel', 'motel', 'rv_park', 'resort'},
            'attraction': {'tourist_attraction'},
            'viewpoint': {'scenic_lookout'},
            'historic': {'historical_landmark'},
            'park': {'campground', 'natural_feature'},
            'trailhead': {'hiking_area', 'natural_feature', 'park'},
            'protected_area': {'park', 'beach', 'campground', 'natural_feature', 'hiking_area'},
            'national_park': {'park', 'natural_feature'},
            'mountain': {'natural_feature'},
            'waterfall': {'natural_feature'},
            'marketplace': {'shopping_mall', 'market'},
        }
        # Bump when POI query behavior changes; used to invalidate stale cache entries.
        self.poi_query_version = 'v8_overpass_progressive_radius'
        # Exclusions for low-value or clearly irrelevant places for watermark context.
        self.poi_excluded_type_tokens = {
            'toilet', 'restroom', 'bathroom', 'public_bath', 'public_toilet',
            'car_repair', 'car_dealer', 'gas_station', 'parking', 'car_wash', 'tire_shop', 'auto_repair_shop',
            'storage', 'post_office', 'funeral_home', 'cemetery',
            'grocery_or_supermarket', 'supermarket', 'convenience_store', 'department_store',
            'bank', 'atm', 'subway_station', 'bus_station', 'transit_station',
            'laundry', 'dry_cleaning', 'hair_care', 'store', 'shopping_mall'
        }
        self.poi_excluded_name_tokens = {
            'toilet', 'restroom', 'washroom', 'public toilet', 'porta potty', 'portable toilet',
            'tire', 'auto repair', 'car wash', 'gas station', 'superstore', 'grocery', 'costco', 'walmart',
            'atm', 'bank', 'laundromat'
        }
        # Exclude ad/listing style names that are not meaningful POIs for watermarking.
        self.poi_listing_noise_tokens = {
            'monthly rates', 'rates negotiable', 'luxury condo', 'corner-suite',
            'make yourself at home', 'sq.ft', 'pets ok', 'pet friendly',
            'book now', 'airbnb', 'vrbo', 'short term rental'
        }
        self.poi_use_heading = bool(poi_cfg.get('use_heading_filter', False))
        self.poi_fov_deg = float(poi_cfg.get('fov_degrees', 60))
        self.poi_max_distance_m = int(poi_cfg.get('max_distance_m', self.poi_radius_m))
        self.poi_heading_weight = float(poi_cfg.get('heading_weight', 0.7))
        self.poi_distance_weight = float(poi_cfg.get('distance_weight', 0.3))

    def _get_google_places_api_key(self) -> Optional[str]:
        """Load Google Places API key from config or environment."""
        poi_cfg = self.config.get('metadata_extraction', {}).get('poi_enrichment', {})
        geocoding_cfg = self.config.get('metadata_extraction', {}).get('geocoding', {})
        return (
            poi_cfg.get('google_api_key') or
            geocoding_cfg.get('google_api_key') or
            os.getenv('GOOGLE_MAPS_API_KEY') or
            os.getenv('GOOGLE_PLACES_API_KEY')
        )
        
    def _load_cache(self) -> Dict:
        """Load geocoding cache from disk"""
        if not self.cache_enabled:
            return {}
        
        cache_path = Path(self.cache_file)
        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    raw = json.load(f)
                return self._normalize_cache_schema(raw)
            except Exception as e:
                print(f"Warning: Could not load cache: {e}")
        return {}

    def _normalize_cache_schema(self, raw_cache: Dict) -> Dict:
        """Normalize legacy cache records without writing to master.json."""
        if not isinstance(raw_cache, dict):
            return {}

        normalized = {}
        for key, entry in raw_cache.items():
            if not isinstance(entry, dict):
                continue

            e = dict(entry)

            photos = e.get('photos', [])
            if isinstance(photos, list):
                e['photos'] = sorted({str(p) for p in photos if p})

            nearby_pois = e.get('nearby_pois')
            poi_search = e.get('poi_search')
            if isinstance(poi_search, dict):
                if nearby_pois is None:
                    nearby_pois = []
                    e['nearby_pois'] = nearby_pois
                if 'result_count' not in poi_search:
                    poi_search['result_count'] = len(nearby_pois)
                if 'status' not in poi_search:
                    if nearby_pois:
                        poi_search['status'] = 'success'
                        poi_search['error'] = None
                    else:
                        poi_search['status'] = 'legacy_unknown'
                        poi_search['error'] = 'legacy_unknown'
                e['poi_search'] = poi_search

            normalized[key] = e

        return normalized
    
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
        """Convert coordinates to location using Photon (primary) with Google Maps fallback"""
        # Check cache first
        cache_key = f"{lat:.6f},{lon:.6f}"
        if cache_key in self.cache:
            location_info = self.cache[cache_key].copy()
            # Strip POI fields from cached data (they belong in separate cache fields)
            location_info.pop('nearby_pois', None)
            location_info.pop('poi_search', None)
            location_info.pop('photos', None)
            return location_info

        # Dev mode: cache-only short circuit
        if self.cache_only:
            return None
        
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        
        # Try Photon first (free, better POI accuracy)
        location_info = self._photon_geocode(lat, lon)
        
        # Fallback to Google Maps if Photon fails and API key available
        if not location_info:
            google_key = self.geocoding_config.get('google_api_key')
            if google_key:
                location_info = self._google_maps_geocode(lat, lon, google_key)
        
        # Final fallback to Nominatim (original provider)
        if not location_info:
            location_info = self._nominatim_geocode(lat, lon)
        
        # Cache the result if we got one
        if location_info:
            # Only cache location data here - POI data added later in extract_metadata
            # Remove POI fields if they exist (legacy data)
            location_info.pop('nearby_pois', None)
            location_info.pop('poi_search', None)
            self.cache[cache_key] = location_info
            self._save_cache()
        
        return location_info
    
    def _photon_geocode(self, lat: float, lon: float) -> Optional[Dict]:
        """Photon by Komoot - Free OSM-based geocoding with good POI accuracy"""
        try:
            # First try reverse with multiple results to find POIs
            url = "https://photon.komoot.io/reverse"
            params = {
                'lat': lat,
                'lon': lon,
                'limit': 10,
                'radius': 0.05  # 50m
            }
            
            response = requests.get(url, params=params, timeout=10)
            self.last_request_time = time.time()
            
            if response.status_code == 200:
                data = response.json()
                features = data.get('features', [])
                
                if features:
                    # Low-quality POI types to reject (generic chains, mundane businesses)
                    low_quality_types = {
                        'convenience', 'supermarket', 'fast_food', 'fuel', 'atm', 
                        'bank', 'pharmacy', 'post_office', 'car_rental', 'parking',
                        'clothes', 'shoes', 'hairdresser', 'laundry', 'car_wash'
                    }
                    
                    # Generic chain names to reject
                    chain_keywords = {
                        '7-eleven', 'seven eleven', 'starbucks', 'mcdonalds', "mcdonald's",
                        'subway', 'tim hortons', 'circle k', 'shell', 'chevron', 'esso',
                        'walmart', 'target', 'costco', 'safeway', 'shoppers drug mart',
                        'cvs', 'walgreens', 'atm', 'parking', 'gas station'
                    }
                    
                    # Look for high-quality POIs (tourism, landmarks, restaurants, parks)
                    for feature in features:
                        props = feature.get('properties', {})
                        osm_key = props.get('osm_key', '')
                        osm_value = props.get('osm_value', '')
                        name = props.get('name', '')
                        
                        if not name:
                            continue
                        
                        # Skip low-quality POI types
                        if osm_value in low_quality_types:
                            continue
                        
                        # Skip generic chain stores
                        name_lower = name.lower()
                        if any(chain in name_lower for chain in chain_keywords):
                            continue
                        
                        # Accept high-quality POIs
                        if osm_key in ['tourism', 'leisure']:
                            # Tourism and leisure are always good
                            return self._photon_feature_to_location(feature, lat, lon, poi_found=True)
                        
                        if osm_key == 'amenity' and osm_value not in low_quality_types:
                            # Good amenities (restaurants, cafes, museums, theaters, etc.)
                            return self._photon_feature_to_location(feature, lat, lon, poi_found=True)
                        
                        if osm_key == 'shop' and osm_value not in low_quality_types:
                            # Named shops that aren't generic (boutiques, galleries, etc.)
                            return self._photon_feature_to_location(feature, lat, lon, poi_found=True)
                    
                    # No quality POI found, use first result without POI flag
                    return self._photon_feature_to_location(features[0], lat, lon, poi_found=False)
        
        except Exception as e:
            print(f"Photon geocoding error ({lat}, {lon}): {e}")
        
        return None
    
    def _photon_feature_to_location(self, feature: Dict, lat: float, lon: float, poi_found: bool = False) -> Dict:
        """Convert Photon feature to standard location format"""
        props = feature.get('properties', {})
        
        return {
            'city': props.get('city') or props.get('town') or props.get('village'),
            'state': props.get('state'),
            'country': props.get('country'),
            'country_code': props.get('countrycode', '').upper() if props.get('countrycode') else None,
            'display_name': props.get('name', '') or f"{props.get('street', '')}, {props.get('city', '')}",
            'name': props.get('name'),  # POI name if available
            'road': props.get('street'),  # Street/road name
            'lat': lat,
            'lon': lon,
            'osm_type': props.get('osm_type'),
            'osm_id': props.get('osm_id'),
            'type': props.get('osm_value') or props.get('type'),
            'poi_found': poi_found,
            'provider': 'photon',
            'namedetails': {},
            'extratags': {}
        }
    
    def _nominatim_geocode(self, lat: float, lon: float) -> Optional[Dict]:
        """OpenStreetMap Nominatim - Fallback provider"""
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
                
                # Check if this is a real POI and not a named road/administrative feature.
                osm_type = data.get('type', '')
                osm_category = data.get('category', '')
                has_name = bool(namedetails.get('name'))
                non_poi_types = {
                    'residential', 'road', 'path', 'track', 'footway', 'cycleway',
                    'tertiary', 'secondary', 'primary', 'unclassified', 'service',
                    'living_street', 'pedestrian'
                }
                non_poi_categories = {'highway', 'boundary', 'place', 'landuse'}
                is_poi = has_name and osm_category not in non_poi_categories and osm_type not in non_poi_types
                
                return {
                    'city': address.get('city') or address.get('town') or address.get('village') or address.get('hamlet') or address.get('suburb'),
                    'state': address.get('state'),
                    'country': address.get('country'),
                    'country_code': address.get('country_code'),
                    'display_name': data.get('display_name'),
                    'road': address.get('road') or address.get('pedestrian') or address.get('footway'),
                    'lat': lat,
                    'lon': lon,
                    'osm_type': data.get('osm_type'),
                    'osm_id': data.get('osm_id'),
                    'category': osm_category,
                    'type': data.get('type'),
                    'poi_found': is_poi,
                    'provider': 'nominatim',
                    'namedetails': namedetails,
                    'extratags': {k: extratags.get(k) for k in ['wikidata','wikipedia','brand','operator'] if k in extratags}
                }
            else:
                print(f"Nominatim API error: {response.status_code}")
                
        except Exception as e:
            print(f"Error reverse geocoding with Nominatim ({lat}, {lon}): {e}")
        
        return None
    
    def _google_maps_geocode(self, lat: float, lon: float, api_key: str) -> Optional[Dict]:
        """Google Maps - Premium fallback for commercial locations"""
        try:
            # Try Places API first for POI detection
            places_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            
            for radius in [20, 50, 100]:
                places_params = {
                    'location': f"{lat},{lon}",
                    'radius': radius,
                    'key': api_key
                }
                
                places_response = requests.get(places_url, params=places_params, timeout=10)
                if places_response.status_code == 200:
                    places_data = places_response.json()
                    
                    if places_data.get('status') == 'OK' and places_data.get('results'):
                        # Filter out administrative areas
                        excluded_types = {'locality', 'political', 'administrative_area_level_1', 
                                        'administrative_area_level_2', 'administrative_area_level_3',
                                        'country', 'postal_code', 'neighborhood'}
                        
                        for poi in places_data['results']:
                            poi_types = set(poi.get('types', []))
                            if not poi_types.issubset(excluded_types) and poi_types - excluded_types:
                                # Found actual business/POI
                                address_components = {}
                                for comp in poi.get('address_components', []):
                                    comp_type = comp['types'][0] if comp.get('types') else None
                                    if comp_type:
                                        address_components[comp_type] = comp.get('long_name')
                                
                                return {
                                    'city': address_components.get('locality'),
                                    'state': address_components.get('administrative_area_level_1'),
                                    'country': address_components.get('country'),
                                    'country_code': address_components.get('country', '').upper()[:2],
                                    'display_name': poi.get('vicinity', ''),
                                    'name': poi.get('name'),
                                    'lat': lat,
                                    'lon': lon,
                                    'type': poi.get('types', [None])[0],
                                    'poi_found': True,
                                    'provider': 'google',
                                    'namedetails': {},
                                    'extratags': {}
                                }
                        break
            
            # Fallback to regular geocoding
            geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                'latlng': f"{lat},{lon}",
                'key': api_key
            }
            
            response = requests.get(geocode_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'OK' and data.get('results'):
                    result = data['results'][0]
                    address_components = {}
                    for comp in result.get('address_components', []):
                        comp_type = comp['types'][0] if comp.get('types') else None
                        if comp_type:
                            address_components[comp_type] = comp.get('long_name')
                    
                    return {
                        'city': address_components.get('locality'),
                        'state': address_components.get('administrative_area_level_1'),
                        'country': address_components.get('country'),
                        'country_code': address_components.get('country', '').upper()[:2],
                        'display_name': result.get('formatted_address', ''),
                        'lat': lat,
                        'lon': lon,
                        'type': result.get('types', [None])[0],
                        'provider': 'google',
                        'namedetails': {},
                        'extratags': {}
                    }
        
        except Exception as e:
            print(f"Google Maps geocoding error ({lat}, {lon}): {e}")
        
        return None

    def _should_refresh_cached_pois(self, cached_data: Dict) -> bool:
        """Decide whether cached POI data should be refreshed.

        Retry empty legacy caches and transient failures, but keep stable empty results.
        """
        nearby_pois = cached_data.get('nearby_pois')
        poi_search = cached_data.get('poi_search') or {}
        status = poi_search.get('status')
        error = poi_search.get('error')

        if nearby_pois is None or 'poi_search' not in cached_data:
            return True

        # Refresh when POI query strategy changed (radius/categories),
        # so stale wide-radius results don't stick forever.
        cached_radius = poi_search.get('search_radius_m')
        cached_categories = poi_search.get('categories') or []
        cached_query_version = poi_search.get('query_version')
        if cached_radius is not None and int(cached_radius) != int(self.poi_radius_m):
            return True
        if set(map(str, cached_categories)) != set(map(str, self.poi_allowed_categories)):
            return True
        if cached_query_version != self.poi_query_version:
            return True

        if nearby_pois:
            return False

        retryable_statuses = {
            None,
            'legacy_unknown',
            'rate_limited',
            'backoff_active',
            'timeout',
            'missing_api_key',
            'api_forbidden',
            'api_unavailable',
            'request_error',
        }
        return status in retryable_statuses or error in retryable_statuses

    def _is_excluded_place(self, place: Dict) -> bool:
        """Return True for low-value places we never want in watermark context."""
        types = [str(t).lower() for t in (place.get('types') or [])]
        name = (place.get('name') or '').lower()
        vicinity = (place.get('vicinity') or '').lower()
        haystack = f"{name} {vicinity}"

        if any(tok in types for tok in self.poi_excluded_type_tokens):
            return True
        if any(tok in haystack for tok in self.poi_excluded_name_tokens):
            return True
        if any(tok in haystack for tok in self.poi_listing_noise_tokens):
            return True
        # Heuristic: very long promo-like names with pricing/symbol noise are usually listings.
        if len(name) > 72 and any(sym in name for sym in ['$', '@']):
            return True
        return False

    def _match_allowed_category(self, google_types: List[str], place: Optional[Dict] = None, query_category: Optional[str] = None) -> Optional[str]:
        """Return configured category that matches Google types, using alias map."""
        for gtype in google_types:
            if gtype in self.poi_allowed_categories:
                return gtype

        # Alias-based matching: configured category -> equivalent Google types.
        for configured in self.poi_allowed_categories:
            aliases = self.poi_category_aliases.get(configured, set())
            if any(gtype in aliases for gtype in google_types):
                return configured

        # Last-chance token match for mild naming variance.
        for gtype in google_types:
            for configured in self.poi_allowed_categories:
                if configured in gtype or gtype in configured:
                    return configured

        # Query-context fallback: for natural/outdoor categories, Google often
        # returns generic types only; use name/vicinity hints before discarding.
        if place and query_category:
            hay = f"{(place.get('name') or '').lower()} {(place.get('vicinity') or '').lower()}"
            query_hints = {
                'trailhead': ['trail', 'trailhead', 'hike', 'hiking'],
                'park': ['park'],
                'protected_area': ['park', 'reserve', 'conservation', 'landing', 'nature'],
                'national_park': ['national park', 'park'],
                'beach': ['beach'],
                'mountain': ['mountain', 'mt '],
                'peak': ['peak'],
                'waterfall': ['waterfall', 'falls'],
            }
            hints = query_hints.get(query_category, [])
            if any(h in hay for h in hints):
                return query_category
        return None

    def fetch_pois(self, lat: float, lon: float, heading_deg: Optional[float] = None) -> List[Dict]:
        """Fetch nearby POIs from Overpass using progressive radius strategy."""
        self.last_poi_fetch_status = 'not_attempted'
        if not self.poi_enabled:
            self.last_poi_fetch_status = 'disabled'
            return []

        # Keep spacing between batches to avoid hammering Overpass.
        elapsed = time.time() - self.last_poi_request_time
        if elapsed < self.poi_request_delay_s:
            time.sleep(self.poi_request_delay_s - elapsed)

        print(f"   🔄 Overpass nearby search (radii: {self.poi_progressive_radii})")

        try:
            pois: List[Dict] = []
            for radius_m in self.poi_progressive_radii:
                primary = get_nearby_interesting_pois(lat, lon, radius_m=radius_m)
                if primary:
                    merged = primary
                else:
                    natural = get_natural_context_pois(lat, lon, radius_m=max(radius_m, 250))
                    merged = _merge_poi_lists(primary, natural)

                # Filter to allowed categories when configured.
                if self.poi_allowed_categories:
                    allowed = set(self.poi_allowed_categories)
                    filtered = [p for p in merged if (p.get('type') or '').lower() in allowed]
                    # Fallback to merged if filtering removed everything; keeps robust defaults.
                    merged = filtered or merged

                # GeoExtractor cache schema historically uses `category` for POI type.
                normalized: List[Dict] = []
                for poi in merged:
                    poi_type = (poi.get('type') or '').lower()
                    normalized.append({
                        'name': poi.get('name', 'Unnamed'),
                        'category': poi_type,
                        'type': poi_type,
                        'distance_m': round(float(poi.get('distance_m') or 0), 1),
                        'bearing_deg': poi.get('bearing_deg'),
                        'bearing_cardinal': poi.get('bearing_cardinal'),
                        'wikidata': (poi.get('tags') or {}).get('wikidata'),
                    })

                normalized.sort(key=lambda x: x['distance_m'])
                pois = normalized[:self.poi_max_results]

                print(f"   --> POI @ {radius_m}m")
                if pois:
                    print(f"      {[p.get('name') for p in pois]}")
                    print(f"      ✅ Relevant local POIs found at {radius_m}m; skipping larger radii")
                    break
                print("      []")
                print(f"      ⏭️  No relevant POIs at {radius_m}m; trying next radius")

            self.last_poi_request_time = time.time()
            self.last_poi_fetch_status = 'success' if pois else 'no_pois_found'
            print(f"   ✅ Overpass returned {len(pois)} POIs")
            return pois
        except requests.exceptions.Timeout:
            self.last_poi_fetch_status = 'timeout'
            return []
        except Exception:
            self.last_poi_fetch_status = 'request_error'
            return []
    
    def _calculate_distance_exact(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """EXACT distance calculation from debug/test_ollama_structured.py calculate_distance()"""
        import math
        R = 6371000  # Earth's radius in meters
        
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c

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

    def format_display_name_english(self, location_info: Optional[Dict]) -> str:
        """Format location using English names from namedetails when available.
        
        Extracts readable location from display_name, using English translations
        from namedetails.name:en when available for non-Latin scripts.
        
        Returns format like: "Hikagesawa Forest Road, Hachiōji, Tokyo, Japan"
        """
        if not location_info:
            return "Unknown Location"
        
        display_name = location_info.get('display_name', '')
        if not display_name:
            return self.format_location(location_info)  # Fallback to short format
        
        # Parse display_name components (comma-separated)
        parts = [p.strip() for p in display_name.split(',')]
        
        # Get English name if available
        namedetails = location_info.get('namedetails', {})
        english_name = namedetails.get('name:en')
        
        # If we have English name, replace first part (often the street/landmark name)
        if english_name and len(parts) > 0:
            parts[0] = english_name
        
        # For Japan specifically, translate common terms
        country_code = location_info.get('country_code', '').upper()
        if country_code == 'JP':
            # Replace Japanese administrative divisions with English
            translated_parts = []
            for part in parts:
                # Keep first part (already English if available)
                if part == parts[0] and english_name:
                    translated_parts.append(part)
                    continue
                # Keep numeric parts (postal codes)
                if part.replace('-', '').isdigit():
                    translated_parts.append(part)
                    continue
                # Try to extract English from mixed scripts or keep if already Latin
                if any(ord(c) < 128 for c in part):  # Has Latin characters
                    translated_parts.append(part)
                else:
                    # Skip purely Kanji parts, we'll use city/state from address
                    continue
            
            # Rebuild with address components for missing translations
            address = location_info.get('address', {}) if 'address' in location_info else location_info
            city = address.get('city') or address.get('town') or address.get('village')
            state = address.get('state')
            country = address.get('country')
            
            # Build clean English-friendly location
            result_parts = []
            if translated_parts:
                result_parts.extend(translated_parts[:2])  # Street name + maybe one more
            if city and city not in result_parts:
                result_parts.append(city)
            if country:
                result_parts.append(country)
            
            return ', '.join(result_parts) if result_parts else "Unknown Location"
        
        # For other countries, return first 3-4 meaningful parts
        meaningful_parts = [p for p in parts[:4] if p and not p.replace('-', '').isdigit()]
        return ', '.join(meaningful_parts) if meaningful_parts else self.format_location(location_info)
    
    def format_location(self, location_info: Optional[Dict]) -> str:
        """Format location info into a short, readable string with neighborhood detail
        
        Rules:
        - North America (USA/Canada): Use state/province abbreviations, omit country
          Example: "Denver, CO" not "Denver, Colorado, United States"
        - Other countries with neighborhoods: Show neighborhood detail
          Example: "Shibuya, Tokyo" not just "Tokyo, Japan"
        - Fallback: city, country
        """
        if not location_info:
            return "Unknown Location"
        
        # Extract all available location components
        address = location_info.get('address', {}) if 'address' in location_info else location_info
        
        # Get location hierarchy (from specific to general)
        neighbourhood = address.get('neighbourhood') or address.get('suburb') or address.get('quarter')
        city = location_info.get('city') or address.get('city') or address.get('town') or address.get('village')
        state = location_info.get('state') or address.get('state')
        country = location_info.get('country') or address.get('country')
        country_code = (location_info.get('country_code') or address.get('country_code') or '').upper()
        
        # Check if this is North America (USA or Canada)
        is_north_america = country_code in ['US', 'CA']
        
        if is_north_america:
            # North America: Use abbreviations, omit country
            if city and state:
                state_abbrev = self.STATE_ABBREVIATIONS.get(state, state)
                # Add neighborhood if available and different from city
                if neighbourhood and neighbourhood != city:
                    return f"{neighbourhood}, {city}, {state_abbrev}"
                return f"{city}, {state_abbrev}"
            elif city:
                return city
            elif state:
                state_abbrev = self.STATE_ABBREVIATIONS.get(state, state)
                return state_abbrev
            else:
                return "Unknown Location"
        else:
            # Other countries: Show neighborhood detail when available
            if neighbourhood and city and neighbourhood != city:
                # Show neighborhood + city for detail (e.g., "Shibuya, Tokyo")
                return f"{neighbourhood}, {city}"
            elif city and country:
                return f"{city}, {country}"
            elif city:
                return city
            elif country:
                return country
            else:
                return "Unknown Location"
    
    def extract_minimal_exif(self, image_path: str) -> Dict:
        """
        Extract ONLY essential EXIF metadata from image
        Returns minimal dictionary with date_taken ONLY
        
        GPS data (altitude, direction) goes in top-level 'gps' node
        Geocoding results go in top-level 'location' node
        This keeps EXIF clean - not a dump ground!
        """
        exif_dict = {}
        
        try:
            image = Image.open(image_path)
            exif_data = image._getexif()
            
            if not exif_data:
                return exif_dict
            
            # ONLY extract DateTimeOriginal/Digitized/DateTime for date_taken
            # GPS fields extracted separately into top-level 'gps' node by extract_metadata()
            for tag, value in exif_data.items():
                decoded = TAGS.get(tag, tag)
                
                # Extract ONLY date/time fields
                if decoded == 'DateTimeOriginal':
                    try:
                        dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        exif_dict['date_time_original'] = dt.isoformat()
                    except:
                        exif_dict['date_time_original'] = value
                
                elif decoded == 'DateTimeDigitized':
                    try:
                        dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        exif_dict['date_time_digitized'] = dt.isoformat()
                    except:
                        exif_dict['date_time_digitized'] = value
                
                elif decoded == 'DateTime':
                    try:
                        dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        exif_dict['date_time'] = dt.isoformat()
                    except:
                        exif_dict['date_time'] = value
            
        except Exception as e:
            print(f"Warning: Could not extract minimal EXIF from {image_path}: {e}")
        
        return exif_dict
    
    def extract_gps_data(self, image_path: str) -> Dict:
        """
        Extract GPS data into dedicated GPS node
        Returns: {'lat': float, 'lon': float, 'altitude': float, 'heading': float, 'cardinal': str}
        Separate from EXIF dump - clear node structure!
        """
        gps_dict = {}
        
        try:
            image = Image.open(image_path)
            exif_data = image._getexif()
            
            if not exif_data:
                return gps_dict
            
            for tag, value in exif_data.items():
                decoded = TAGS.get(tag, tag)
                
                if decoded == "GPSInfo":
                    gps_info = {}
                    for gps_tag in value:
                        sub_decoded = GPSTAGS.get(gps_tag, gps_tag)
                        gps_val = value[gps_tag]
                        # Convert bytes in GPS fields
                        if isinstance(gps_val, bytes):
                            try:
                                gps_val = gps_val.decode('utf-8', errors='ignore').strip('\x00')
                            except:
                                continue
                        gps_info[sub_decoded] = gps_val
                    
                    # Extract GPS altitude
                    altitude = self._convert_rational(gps_info.get('GPSAltitude'))
                    altitude_ref = gps_info.get('GPSAltitudeRef', 0)  # Default to 0 (above sea level)
                    if altitude is not None:
                        # GPSAltitudeRef: 0 = above sea level, 1 = below sea level
                        # Most photos are above sea level, so default to positive
                        gps_dict['altitude'] = -altitude if altitude_ref == 1 else altitude
                    
                    # Extract GPS heading/direction
                    heading = self._convert_rational(gps_info.get('GPSImgDirection'))
                    if heading is not None:
                        gps_dict['heading'] = heading
                        gps_dict['cardinal'] = self._degrees_to_compass(heading)
                        gps_dict['heading_ref'] = gps_info.get('GPSImgDirectionRef')
                    
                    # Extract lat/lon coordinates
                    coords = self.extract_gps_from_exif(image_path)
                    if coords:
                        lat, lon = coords
                        gps_dict['lat'] = lat
                        gps_dict['lon'] = lon
            
        except Exception as e:
            print(f"Warning: Could not extract GPS data from {image_path}: {e}")
        
        return gps_dict
    
    def extract_metadata(self, image_path: str) -> Dict:
        """
        Extract minimal, clean metadata from image
        
        Schema:
        - date_taken: from EXIF DateTimeOriginal (EXIF source)
        - gps: {lat, lon, altitude, heading, cardinal} (EXIF source)
        - location: {city, state, country, formatted} (Geocoding result from reverse lookup)
        
        Clear separation: EXIF data vs. Geocoding results!
        """
        metadata = {
            'file_path': str(image_path),
            'file_name': Path(image_path).name,
            'timestamp': utc_now_iso_z(),
            'date_taken': None,
            'date_taken_utc': None,
            'gps': None,
            'location': None
        }
        
        # Extract MINIMAL EXIF data (only DateTimeOriginal)
        exif_data = self.extract_minimal_exif(image_path)
        
        # Extract primary date_taken from EXIF (prefer DateTimeOriginal)
        if 'date_time_original' in exif_data:
            metadata['date_taken'] = exif_data['date_time_original']
        elif 'date_time_digitized' in exif_data:
            metadata['date_taken'] = exif_data['date_time_digitized']
        elif 'date_time' in exif_data:
            metadata['date_taken'] = exif_data['date_time']
        
        # Extract GPS data into dedicated 'gps' node (clear separation!)
        gps_data = self.extract_gps_data(image_path)
        
        if gps_data and 'lat' in gps_data and 'lon' in gps_data:
            metadata['gps'] = gps_data
            
            lat, lon = gps_data['lat'], gps_data['lon']
            cache_key = f"{lat:.6f},{lon:.6f}"
            
            # If we have a local date and GPS, infer UTC capture time
            if metadata.get('date_taken'):
                inferred = infer_utc_from_local_naive(metadata['date_taken'], lat, lon)
                if inferred:
                    metadata['date_taken_utc'] = inferred

            # Reverse geocode to get location (city / state / country)
            location_info = self.reverse_geocode(lat, lon)
            if location_info:
                location_info['formatted'] = self.format_location(location_info)
                metadata['location'] = location_info

            # Track which photos map to each coordinate in geocode_cache.json.
            # This stays out of master.json and helps validate duplicate geolocation clusters.
            if self.cache_enabled:
                cached_data = self.cache.get(cache_key, {})
                photos = cached_data.get('photos', [])
                photo_name = Path(image_path).name
                if photo_name not in photos:
                    photos.append(photo_name)
                    photos.sort()
                cached_data['photos'] = photos
                self.cache[cache_key] = cached_data
                self._save_cache()

            # Optional POI enrichment for programmatic watermark context.
            # Stored ONLY in geocode_cache.json (never in master.json).
            if self.poi_enabled and self.cache_enabled:
                cached_data = self.cache.get(cache_key, {})
                if self._should_refresh_cached_pois(cached_data):
                    nearby_pois = self.fetch_pois(lat, lon, heading_deg=gps_data.get('heading'))
                    poi_status = self.last_poi_fetch_status or 'legacy_unknown'
                    cached_data['nearby_pois'] = nearby_pois
                    cached_data['poi_search'] = {
                        'attempted': True,
                        'search_radius_m': self.poi_radius_m,
                        'search_radii_m': self.poi_progressive_radii,
                        'query_version': self.poi_query_version,
                        'max_results': self.poi_max_results,
                        'categories': self.poi_allowed_categories,
                        'status': poi_status,
                        'result_count': len(nearby_pois),
                        'error': None if nearby_pois else poi_status
                    }
                    self.cache[cache_key] = cached_data
                    self._save_cache()
        
        return metadata
