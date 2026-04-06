"""
Geolocation Metadata Extractor
Extracts GPS coordinates from EXIF and reverse geocodes to human-readable locations
"""
import json
import os
import time
from threading import Lock
from datetime import datetime
from utils.time_utils import utc_now_iso_z, infer_utc_from_local_naive
from pathlib import Path
from typing import Any, Optional, Dict, Tuple, List
import requests
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from .poi_osm_queries import get_nearby_interesting_pois, get_natural_context_pois, _merge_poi_lists
from .poi_overpass import get_overpass_stats, reset_overpass_stats

class GeoExtractor:
    def __init__(self, config: Dict):
        self.config = config
        self._load_env_file_once()
        metadata_cfg = config.get('metadata_extraction', {})
        providers_cfg = metadata_cfg.get('providers', {}) if isinstance(metadata_cfg.get('providers', {}), dict) else {}

        # Backward-compatible geocoding settings (legacy: metadata_extraction.geocoding)
        legacy_geo_cfg = metadata_cfg.get('geocoding', {}) if isinstance(metadata_cfg.get('geocoding', {}), dict) else {}
        geocoding_cfg = providers_cfg.get('geocoding', {}) if isinstance(providers_cfg.get('geocoding', {}), dict) else {}
        geocoding_providers = geocoding_cfg.get('providers', {}) if isinstance(geocoding_cfg.get('providers', {}), dict) else {}
        cache_cfg = geocoding_cfg.get('cache', {}) if isinstance(geocoding_cfg.get('cache', {}), dict) else {}

        active_provider = str(
            geocoding_cfg.get('active_provider')
            or legacy_geo_cfg.get('provider')
            or 'nominatim'
        ).lower().strip()
        provider_order = geocoding_cfg.get('provider_order')
        if not isinstance(provider_order, list) or not provider_order:
            provider_order = [active_provider]
        normalized_order: List[str] = []
        for provider in provider_order:
            p = str(provider).lower().strip()
            if p == 'google':
                p = 'google_maps'
            if p and p not in normalized_order:
                normalized_order.append(p)
        if active_provider == 'google':
            active_provider = 'google_maps'
        if active_provider and active_provider not in normalized_order:
            normalized_order.insert(0, active_provider)

        self.geocoding_provider = active_provider
        self.geocoding_provider_order = normalized_order or ['nominatim']
        self.geocoding_allow_fallback = bool(geocoding_cfg.get('allow_fallback', True))

        self.geocoding_config = legacy_geo_cfg
        self.cache_enabled = bool(cache_cfg.get('enabled', legacy_geo_cfg.get('cache_enabled', True)))
        self.cache_file = cache_cfg.get('file', legacy_geo_cfg.get('cache_file', 'geocode_cache.json'))
        self.cache_only = bool(cache_cfg.get('cache_only', legacy_geo_cfg.get('cache_only', False)))
        self.rate_limit = float(geocoding_cfg.get('request_delay_seconds', legacy_geo_cfg.get('rate_limit_seconds', 1.0)))
        self.user_agent = geocoding_cfg.get('user_agent', legacy_geo_cfg.get('user_agent', 'SkiCycleRun/1.0'))

        nominatim_cfg = geocoding_providers.get('nominatim', {}) if isinstance(geocoding_providers.get('nominatim', {}), dict) else {}
        self.nominatim_api_url = nominatim_cfg.get('api_url', legacy_geo_cfg.get('api_url', 'https://nominatim.openstreetmap.org/reverse'))
        self.nominatim_zoom = int(nominatim_cfg.get('zoom', legacy_geo_cfg.get('zoom', 14)))

        google_cfg = geocoding_providers.get('google_maps', {}) if isinstance(geocoding_providers.get('google_maps', {}), dict) else {}
        if not google_cfg and isinstance(geocoding_providers.get('google', {}), dict):
            google_cfg = geocoding_providers.get('google', {})
        self.google_cfg = google_cfg
        self.google_geocode_api_url = google_cfg.get(
            'geocode_api_url',
            'https://maps.googleapis.com/maps/api/geocode/json'
        )
        # Google remains opt-in; defaults keep this pipeline on open-source providers.
        self.google_geocode_enabled = bool(google_cfg.get('enabled', False))
        self.google_geocode_max_calls_per_run = int(google_cfg.get('max_calls_per_run', 0))
        self.google_geocode_calls_this_run = 0
        self._google_requested_photos: set[str] = set()

        self.last_request_time = 0
        self.cache = self._load_cache()
        reset_overpass_stats()

        self.call_stats: Dict[str, int] = {
            'cache_hits': 0,
            'cache_misses': 0,
            'provider_attempts_photon': 0,
            'provider_attempts_nominatim': 0,
            'provider_attempts_google_maps': 0,
            'provider_success_photon': 0,
            'provider_success_nominatim': 0,
            'provider_success_google_maps': 0,
            'provider_skips_google_disabled': 0,
            'provider_skips_google_no_key': 0,
            'provider_skips_google_budget': 0,
            'poi_fetch_invocations': 0,
            'poi_fetch_attempted': 0,
            'poi_fetch_skipped_disabled': 0,
            'poi_fetch_skipped_provider': 0,
            'poi_fetch_skipped_duplicate_photo': 0,
            'poi_fetch_skipped_duplicate_coordinate': 0,
        }

        # POI enrichment config.
        # POIs are cached in geocode_cache.json and intentionally NOT written to master.json.
        legacy_poi_cfg = metadata_cfg.get('poi_enrichment', {}) if isinstance(metadata_cfg.get('poi_enrichment', {}), dict) else {}
        poi_cfg = providers_cfg.get('poi', {}) if isinstance(providers_cfg.get('poi', {}), dict) else {}
        poi_providers = poi_cfg.get('providers', {}) if isinstance(poi_cfg.get('providers', {}), dict) else {}
        poi_search_cfg = poi_cfg.get('search', {}) if isinstance(poi_cfg.get('search', {}), dict) else {}
        overpass_cfg = poi_providers.get('overpass', {}) if isinstance(poi_providers.get('overpass', {}), dict) else {}

        self.poi_enabled = bool(poi_cfg.get('enabled', legacy_poi_cfg.get('enabled', False)))
        self.poi_provider = str(poi_cfg.get('active_provider', 'overpass')).lower().strip() or 'overpass'
        self.poi_radius_m = int(poi_search_cfg.get('radius_m', legacy_poi_cfg.get('radius_m', 50)))
        progressive = poi_search_cfg.get('progressive_radii_m', legacy_poi_cfg.get('progressive_radii_m', [self.poi_radius_m, 120, 250]))
        self.poi_progressive_radii: List[int] = sorted({max(10, int(r)) for r in progressive if r})
        if not self.poi_progressive_radii:
            self.poi_progressive_radii = [self.poi_radius_m]
        self.poi_max_results = int(poi_search_cfg.get('max_results', legacy_poi_cfg.get('max_results', 5)))
        self.poi_timeout_s = int(overpass_cfg.get('timeout_seconds', legacy_poi_cfg.get('timeout_seconds', 15)))
        self.poi_request_delay_s = float(overpass_cfg.get('request_delay_seconds', legacy_poi_cfg.get('request_delay_seconds', 2.0)))
        self.poi_rate_limit_backoff_s = int(overpass_cfg.get('rate_limit_backoff_seconds', legacy_poi_cfg.get('rate_limit_backoff_seconds', 60)))
        self.poi_single_call_per_photo = bool(poi_cfg.get('single_call_per_photo', True))
        self.poi_dedupe_per_coordinate_per_run = bool(poi_cfg.get('dedupe_per_coordinate_per_run', True))
        self.last_poi_request_time = 0.0
        self.poi_backoff_until = 0.0
        self.last_poi_fetch_status = 'not_attempted'
        configured_categories = [c.lower() for c in poi_search_cfg.get('categories', legacy_poi_cfg.get('categories', [])) if c]
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
        self.poi_use_heading = bool(poi_search_cfg.get('use_heading_filter', legacy_poi_cfg.get('use_heading_filter', False)))
        self.poi_fov_deg = float(poi_search_cfg.get('fov_degrees', legacy_poi_cfg.get('fov_degrees', 60)))
        self.poi_max_distance_m = int(poi_search_cfg.get('max_distance_m', legacy_poi_cfg.get('max_distance_m', self.poi_radius_m)))
        self.poi_heading_weight = float(poi_search_cfg.get('heading_weight', legacy_poi_cfg.get('heading_weight', 0.7)))
        self.poi_distance_weight = float(poi_search_cfg.get('distance_weight', legacy_poi_cfg.get('distance_weight', 0.3)))
        self.last_poi_fallback_context: Optional[Dict[str, Any]] = None
        self._poi_requested_photos: set[str] = set()
        self._poi_requested_coords: set[str] = set()
        self._state_lock = Lock()

    _ENV_LOADED = False

    @classmethod
    def _load_env_file_once(cls) -> None:
        """Load .env into process environment once (without overriding existing vars)."""
        if cls._ENV_LOADED:
            return

        try:
            project_root = Path(__file__).resolve().parent.parent
            env_file = project_root / '.env'
            if env_file.exists():
                with open(env_file, 'r', encoding='utf-8') as handle:
                    for line in handle:
                        line = line.strip()
                        if not line or line.startswith('#') or '=' not in line:
                            continue
                        key, _, value = line.partition('=')
                        key = key.strip()
                        value = value.strip()
                        if key and key not in os.environ:
                            os.environ[key] = value
        except Exception:
            # .env loading is best-effort; normal env vars still work.
            pass

        cls._ENV_LOADED = True

    def _get_google_places_api_key(self) -> Optional[str]:
        """Load Google API key from environment only (never from JSON config)."""
        metadata_cfg = self.config.get('metadata_extraction', {})
        providers_cfg = metadata_cfg.get('providers', {}) if isinstance(metadata_cfg.get('providers', {}), dict) else {}
        geocoding_unified = providers_cfg.get('geocoding', {}) if isinstance(providers_cfg.get('geocoding', {}), dict) else {}
        geocoding_providers = geocoding_unified.get('providers', {}) if isinstance(geocoding_unified.get('providers', {}), dict) else {}
        google_cfg = geocoding_providers.get('google_maps', {}) if isinstance(geocoding_providers.get('google_maps', {}), dict) else {}
        if not google_cfg and isinstance(geocoding_providers.get('google', {}), dict):
            google_cfg = geocoding_providers.get('google', {})

        env_var_name = google_cfg.get('api_key_env_var')
        env_var_key = os.getenv(str(env_var_name).strip()) if env_var_name else None
        return (
            env_var_key or
            os.getenv('GOOGLE_MAPS_API_KEY') or
            os.getenv('GOOGLE_PLACES_API_KEY')
        )

    def _consume_google_call_budget(self, photo_request_id: Optional[str]) -> bool:
        """Enforce one Google request per photo and optional per-run budget."""
        with self._state_lock:
            if photo_request_id:
                normalized = str(photo_request_id)
                if normalized in self._google_requested_photos:
                    return False
                self._google_requested_photos.add(normalized)

            if self.google_geocode_max_calls_per_run <= 0:
                return False
            if self.google_geocode_calls_this_run >= self.google_geocode_max_calls_per_run:
                return False

            self.google_geocode_calls_this_run += 1
            return True
        
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
    
    def reverse_geocode(self, lat: float, lon: float, photo_request_id: Optional[str] = None) -> Optional[Dict]:
        """Convert coordinates to location using configured provider order."""
        # Check cache first
        cache_key = f"{lat:.6f},{lon:.6f}"
        if cache_key in self.cache:
            self.call_stats['cache_hits'] += 1
            location_info = self.cache[cache_key].copy()
            # Strip POI fields from cached data (they belong in separate cache fields)
            location_info.pop('nearby_pois', None)
            location_info.pop('poi_search', None)
            location_info.pop('photos', None)
            return location_info
        self.call_stats['cache_misses'] += 1

        # Dev mode: cache-only short circuit
        if self.cache_only:
            return None
        
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)

        location_info = None
        providers_to_try = self.geocoding_provider_order or [self.geocoding_provider]
        if not self.geocoding_allow_fallback and providers_to_try:
            providers_to_try = [providers_to_try[0]]

        for provider in providers_to_try:
            normalized = provider.strip().lower()
            if normalized == 'photon':
                location_info = self._photon_geocode(lat, lon)
                if location_info:
                    self.call_stats['provider_success_photon'] += 1
            elif normalized in {'nominatim', 'osm'}:
                location_info = self._nominatim_geocode(lat, lon)
                if location_info:
                    self.call_stats['provider_success_nominatim'] += 1
            elif normalized in {'google', 'google_maps'}:
                if not self.google_geocode_enabled:
                    self.call_stats['provider_skips_google_disabled'] += 1
                    continue
                google_key = self._get_google_places_api_key()
                if not google_key:
                    self.call_stats['provider_skips_google_no_key'] += 1
                    continue
                if not self._consume_google_call_budget(photo_request_id):
                    self.call_stats['provider_skips_google_budget'] += 1
                    continue
                location_info = self._google_maps_geocode(lat, lon, google_key)
                if location_info:
                    self.call_stats['provider_success_google_maps'] += 1

            if location_info:
                break
        
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
            self.call_stats['provider_attempts_photon'] += 1
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
            url = self.nominatim_api_url
            params = {
                'lat': lat,
                'lon': lon,
                'format': 'jsonv2',
                'zoom': int(self.nominatim_zoom),
                'addressdetails': 1,
                'namedetails': 1,
                'extratags': 1
            }
            headers = {
                'User-Agent': self.user_agent
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            self.call_stats['provider_attempts_nominatim'] += 1
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
        """Google Maps geocode fallback with a single request per photo invocation."""
        try:
            geocode_url = self.google_geocode_api_url
            params = {
                'latlng': f"{lat},{lon}",
                'key': api_key
            }

            response = requests.get(geocode_url, params=params, timeout=10)
            self.call_stats['provider_attempts_google_maps'] += 1
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

    def _build_poi_fallback_context(self, location_info: Optional[Dict]) -> Optional[Dict[str, Any]]:
        """Build a concise reverse-geocode fallback when nearby POIs are unavailable."""
        if not location_info:
            return None

        address = location_info.get('address', {}) if 'address' in location_info else location_info
        formatted = (location_info.get('formatted') or self.format_location(location_info) or '').strip()
        anchor = (
            location_info.get('name')
            or location_info.get('road')
            or address.get('road')
            or address.get('pedestrian')
            or address.get('footway')
            or address.get('neighbourhood')
            or address.get('suburb')
            or address.get('quarter')
        )
        anchor = (anchor or '').strip()
        display_name = (location_info.get('display_name') or '').strip()
        place_type = str(location_info.get('type') or location_info.get('category') or 'location').strip()
        provider = str(location_info.get('provider') or 'reverse_geocode').strip()

        if anchor and formatted and anchor.lower() not in formatted.lower():
            summary = f"{anchor}, {formatted}"
        else:
            summary = anchor or formatted or display_name

        if not summary:
            return None

        return {
            'summary': summary,
            'anchor': anchor or None,
            'formatted': formatted or None,
            'display_name': display_name or None,
            'type': place_type,
            'provider': provider,
        }

    def fetch_pois(
        self,
        lat: float,
        lon: float,
        heading_deg: Optional[float] = None,
        location_info: Optional[Dict] = None,
        photo_request_id: Optional[str] = None,
    ) -> List[Dict]:
        """Fetch nearby POIs from Overpass using progressive radius strategy."""
        self.call_stats['poi_fetch_invocations'] += 1
        self.last_poi_fetch_status = 'not_attempted'
        self.last_poi_fallback_context = None
        if not self.poi_enabled:
            self.last_poi_fetch_status = 'disabled'
            self.call_stats['poi_fetch_skipped_disabled'] += 1
            return []
        if self.poi_provider != 'overpass':
            self.last_poi_fetch_status = f"unsupported_provider:{self.poi_provider}"
            self.call_stats['poi_fetch_skipped_provider'] += 1
            return []

        coord_key = f"{lat:.6f},{lon:.6f}"
        with self._state_lock:
            if self.poi_single_call_per_photo and photo_request_id:
                photo_key = str(photo_request_id)
                if photo_key in self._poi_requested_photos:
                    self.last_poi_fetch_status = 'duplicate_photo_request_skipped'
                    self.call_stats['poi_fetch_skipped_duplicate_photo'] += 1
                    return []
                self._poi_requested_photos.add(photo_key)

            if self.poi_dedupe_per_coordinate_per_run:
                if coord_key in self._poi_requested_coords:
                    self.last_poi_fetch_status = 'coordinate_already_queried_this_run'
                    self.call_stats['poi_fetch_skipped_duplicate_coordinate'] += 1
                    return []
                self._poi_requested_coords.add(coord_key)
        self.call_stats['poi_fetch_attempted'] += 1

        # Keep spacing between batches to avoid hammering Overpass.
        elapsed = time.time() - self.last_poi_request_time
        if elapsed < self.poi_request_delay_s:
            time.sleep(self.poi_request_delay_s - elapsed)

        print(f"   🔄 Overpass nearby search (radii: {self.poi_progressive_radii})")

        try:
            pois: List[Dict] = []
            raw_context_preview: List[str] = []
            for radius_m in self.poi_progressive_radii:
                print(f"   • Radius {radius_m}m")
                primary = get_nearby_interesting_pois(lat, lon, radius_m=radius_m, log_prefix='      ')
                if primary:
                    merged = primary
                else:
                    natural = get_natural_context_pois(
                        lat,
                        lon,
                        radius_m=max(radius_m, 250),
                        log_prefix='      ',
                    )
                    merged = _merge_poi_lists(primary, natural)

                raw_context_preview = [
                    poi.get('name', 'Unnamed')
                    for poi in merged[: min(3, self.poi_max_results)]
                    if poi.get('name')
                ]

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

                if pois:
                    for poi in pois:
                        poi_type = poi.get('type') or 'unknown'
                        distance_m = float(poi.get('distance_m') or 0)
                        bearing = poi.get('bearing_cardinal') or ''
                        bearing_suffix = f" {bearing}" if bearing else ''
                        print(
                            f"      • {poi.get('name')} [{poi_type}] "
                            f"({distance_m:.0f}m{bearing_suffix})"
                        )
                    print(f"      ✅ Using {len(pois)} POIs from {radius_m}m radius")
                    break

                if merged:
                    print(
                        f"      · {len(merged)} named OSM candidate(s) found, "
                        "but none matched the watermark filters"
                    )
                    print(f"      · Raw context: {', '.join(raw_context_preview)}")
                else:
                    print("      · No named OSM context found at this radius")
                print(f"      ⏭️  Expanding search beyond {radius_m}m")

            self.last_poi_request_time = time.time()
            self.last_poi_fetch_status = 'success' if pois else 'no_pois_found'
            if not pois:
                self.last_poi_fallback_context = self._build_poi_fallback_context(location_info)
                if self.last_poi_fallback_context:
                    print(
                        "      • Base location: "
                        f"{self.last_poi_fallback_context['summary']} "
                        f"[{self.last_poi_fallback_context['type']}]"
                    )
            print(f"   ✅ Overpass returned {len(pois)} POIs")
            return pois
        except requests.exceptions.Timeout:
            self.last_poi_fetch_status = 'timeout'
            return []
        except Exception:
            self.last_poi_fetch_status = 'request_error'
            return []

    def get_api_call_summary(self) -> Dict[str, Any]:
        """Return API usage summary across geocoding and POI providers."""
        overpass = get_overpass_stats()
        geocoding_attempts = {
            'photon': int(self.call_stats.get('provider_attempts_photon', 0)),
            'nominatim': int(self.call_stats.get('provider_attempts_nominatim', 0)),
            'google_maps': int(self.call_stats.get('provider_attempts_google_maps', 0)),
        }
        geocoding_success = {
            'photon': int(self.call_stats.get('provider_success_photon', 0)),
            'nominatim': int(self.call_stats.get('provider_success_nominatim', 0)),
            'google_maps': int(self.call_stats.get('provider_success_google_maps', 0)),
        }
        geocoding_skips = {
            'google_disabled': int(self.call_stats.get('provider_skips_google_disabled', 0)),
            'google_no_key': int(self.call_stats.get('provider_skips_google_no_key', 0)),
            'google_budget_or_per_photo_limit': int(self.call_stats.get('provider_skips_google_budget', 0)),
        }
        poi_summary = {
            'invocations': int(self.call_stats.get('poi_fetch_invocations', 0)),
            'attempted': int(self.call_stats.get('poi_fetch_attempted', 0)),
            'skipped_disabled': int(self.call_stats.get('poi_fetch_skipped_disabled', 0)),
            'skipped_provider': int(self.call_stats.get('poi_fetch_skipped_provider', 0)),
            'skipped_duplicate_photo': int(self.call_stats.get('poi_fetch_skipped_duplicate_photo', 0)),
            'skipped_duplicate_coordinate': int(self.call_stats.get('poi_fetch_skipped_duplicate_coordinate', 0)),
            'overpass_requests_attempted': int(overpass.get('requests_attempted', 0)),
            'overpass_requests_succeeded': int(overpass.get('requests_succeeded', 0)),
            'overpass_http_errors': int(overpass.get('http_errors', 0)),
            'overpass_timeouts': int(overpass.get('timeouts', 0)),
            'overpass_request_exceptions': int(overpass.get('request_exceptions', 0)),
            'overpass_retry_waits': int(overpass.get('retry_waits', 0)),
            'overpass_queries_failed': int(overpass.get('queries_failed', 0)),
        }

        return {
            'cache': {
                'hits': int(self.call_stats.get('cache_hits', 0)),
                'misses': int(self.call_stats.get('cache_misses', 0)),
            },
            'geocoding': {
                'active_provider': self.geocoding_provider,
                'provider_order': list(self.geocoding_provider_order),
                'attempts': geocoding_attempts,
                'success': geocoding_success,
                'skips': geocoding_skips,
                'google_enabled': bool(self.google_geocode_enabled),
                'google_max_calls_per_run': int(self.google_geocode_max_calls_per_run),
                'google_calls_consumed': int(self.google_geocode_calls_this_run),
            },
            'poi': poi_summary,
        }
    
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
            location_info = self.reverse_geocode(lat, lon, photo_request_id=Path(image_path).name)
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
                    nearby_pois = self.fetch_pois(
                        lat,
                        lon,
                        heading_deg=gps_data.get('heading'),
                        location_info=location_info,
                        photo_request_id=Path(image_path).name,
                    )
                    poi_status = self.last_poi_fetch_status or 'legacy_unknown'
                    cached_data['nearby_pois'] = nearby_pois
                    poi_search = {
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
                    if self.last_poi_fallback_context:
                        poi_search['fallback_context'] = self.last_poi_fallback_context
                    cached_data['poi_search'] = poi_search
                    self.cache[cache_key] = cached_data
                    self._save_cache()
        
        return metadata
