#!/usr/bin/env python3
"""
Compare Multiple Geocoding Services

Test the same coordinates against multiple geocoding providers
to find which gives the best results.

Usage:
  python3 debug/compare_geocoding.py 49.88717777777778 -119.42606388888889
"""
import sys
import json
import requests
from pathlib import Path
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


def nominatim_lookup(lat: float, lon: float) -> dict:
    """OpenStreetMap Nominatim (current provider) with POI search"""
    headers = {'User-Agent': 'SkiCycleRun-Pipeline/1.0'}
    
    # Nominatim doesn't have a good POI search API like Google Places
    # Try multiple approaches: lookup endpoint (for POIs) and reverse at different zooms
    pois_found = []
    
    # First try: Use lookup endpoint which is better for POI discovery
    # Search in expanding bounding boxes around the point
    for radius_deg in [0.0002, 0.0005, 0.001, 0.002]:  # ~20m, 50m, 100m, 200m
        try:
            # Create bounding box around point
            min_lat = lat - radius_deg
            max_lat = lat + radius_deg
            min_lon = lon - radius_deg
            max_lon = lon + radius_deg
            
            # Search for places in this bounding box
            search_params = {
                'format': 'json',
                'viewbox': f'{min_lon},{max_lat},{max_lon},{min_lat}',  # left,top,right,bottom
                'bounded': 1,
                'addressdetails': 1,
                'extratags': 1,
                'namedetails': 1,
                'limit': 10
            }
            
            # Search for common POI types near this location
            for query in ['restaurant', 'cafe', 'shop', 'amenity']:
                search_params['q'] = query
                search_response = requests.get("https://nominatim.openstreetmap.org/search",
                                              params=search_params, headers=headers, timeout=10)
                if search_response.status_code == 200:
                    search_data = search_response.json()
                    if search_data:
                        for item in search_data:
                            item_type = item.get('type', '')
                            name = item.get('name')
                            if name and item_type in ['restaurant', 'cafe', 'bar', 'pub', 'fast_food', 
                                                     'shop', 'attraction', 'hotel']:
                                print(f"   ✓ Found POI in {int(radius_deg*111000)}m radius: {name}")
                                return {
                                    'display_name': item.get('display_name', ''),
                                    'name': name,
                                    'address': item.get('address', {}),
                                    'type': item_type,
                                    'osm_type': item.get('osm_type'),
                                    'poi_found': True
                                }
        except Exception as e:
            continue
    
    # Fallback: Try reverse geocode at different zoom levels
    for zoom in [18, 17, 16, 15]:
        try:
            search_params = {
                'lat': lat,
                'lon': lon,
                'format': 'json',
                'addressdetails': 1,
                'extratags': 1,
                'namedetails': 1,
                'zoom': zoom
            }
            
            search_response = requests.get("https://nominatim.openstreetmap.org/reverse",
                                          params=search_params, headers=headers, timeout=10)
            search_response.raise_for_status()
            search_data = search_response.json()
            
            item_type = search_data.get('type', '')
            name = search_data.get('name')
            
            if name and item_type in ['restaurant', 'cafe', 'bar', 'pub', 'fast_food', 'shop',
                                      'attraction', 'hotel', 'museum', 'park']:
                print(f"   ✓ Found POI at zoom {zoom}: {name}")
                return {
                    'display_name': search_data.get('display_name', ''),
                    'name': name,
                    'address': search_data.get('address', {}),
                    'type': item_type,
                    'osm_type': search_data.get('osm_type'),
                    'poi_found': True
                }
        except Exception as e:
            continue
    
    # Fallback to standard reverse geocoding
    print(f"   ○ No POIs found in 200m radius, using standard reverse geocode")
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        'lat': lat,
        'lon': lon,
        'format': 'json',
        'addressdetails': 1,
        'extratags': 1,
        'namedetails': 1,
        'zoom': 18
    }
    
    response = requests.get(url, params=params, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def photon_lookup(lat: float, lon: float) -> dict:
    """Photon by Komoot (OSM-based, often more accurate) with POI search"""
    # Photon reverse returns multiple results, check for POIs first
    url = "https://photon.komoot.io/reverse"
    params = {
        'lat': lat,
        'lon': lon,
        'limit': 10,  # Get multiple results to find POIs
        'radius': 0.05  # 50m radius
    }
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    if data.get('features'):
        features = data['features']
        print(f"   ✓ Found {len(features)} results")
        
        # Look for actual POIs (amenities, shops, etc)
        for feature in features:
            props = feature.get('properties', {})
            osm_type = props.get('osm_type')
            osm_key = props.get('osm_key', '')
            name = props.get('name')
            
            # Prioritize nodes/ways with names and amenity/shop tags
            if name and osm_key in ['amenity', 'shop', 'tourism', 'leisure']:
                print(f"   ✓ Selected POI: {name} (type: {osm_key}={props.get('osm_value', '')})")
                return {
                    'display_name': props.get('name', ''),
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
                    'osm_type': osm_type,
                    'osm_id': props.get('osm_id'),
                    'type': props.get('osm_value') or props.get('type'),
                    'poi_found': True
                }
        
        # Fallback to first result if no POI found
        print(f"   ○ No POI found, using first result")
        feature = features[0]
        props = feature.get('properties', {})
        
        return {
            'display_name': props.get('name', ''),
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
            'type': props.get('type')
        }
    
    return {'error': 'No results'}


def locationiq_lookup(lat: float, lon: float, api_key: str = None) -> dict:
    """LocationIQ (Enhanced Nominatim with better POI data) with POI search"""
    if not api_key:
        return {'error': 'API key required - get free key at locationiq.com'}
    
    # First try nearby search for POIs
    search_url = "https://us1.locationiq.com/v1/nearby"
    
    for radius in [50, 100, 200, 500]:
        try:
            search_params = {
                'lat': lat,
                'lon': lon,
                'radius': radius,
                'tag': 'amenity,shop,tourism,leisure',  # POI types
                'format': 'json',
                'key': api_key
            }
            
            search_response = requests.get(search_url, params=search_params, timeout=10)
            if search_response.status_code == 200:
                pois = search_response.json()
                if pois and isinstance(pois, list) and len(pois) > 0:
                    print(f"   ✓ Found {len(pois)} POIs within {radius}m")
                    poi = pois[0]
                    return {
                        'display_name': poi.get('display_name', ''),
                        'name': poi.get('name') or poi.get('display_name', '').split(',')[0],
                        'address': poi.get('address', {}),
                        'type': poi.get('type'),
                        'osm_type': poi.get('osm_type'),
                        'poi_found': True
                    }
        except Exception as e:
            print(f"   ○ POI search at {radius}m: {e}")
            continue
    
    print(f"   ○ No POIs found, using reverse geocode")
    url = "https://us1.locationiq.com/v1/reverse"
    params = {
        'lat': lat,
        'lon': lon,
        'format': 'json',
        'addressdetails': 1,
        'extratags': 1,
        'namedetails': 1,
        'normalizeaddress': 1,
        'key': api_key
    }
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def google_maps_lookup(lat: float, lon: float, api_key: str = None) -> dict:
    """Google Maps Geocoding + Places Nearby (Most accurate, commercial grade)"""
    if not api_key:
        return {'error': 'API key required'}
    
    # First, try Places Nearby Search to find POI at this location
    # Try multiple radii to find nearest POI
    # Note: Cannot use 'rankby=distance' with 'radius' parameter
    places_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    
    pois_found = []
    places_data = None
    
    for radius in [20, 50, 100, 200, 500]:  # Try expanding radius
        places_params = {
            'location': f"{lat},{lon}",
            'radius': radius,
            'key': api_key
        }
        
        try:
            places_response = requests.get(places_url, params=places_params, timeout=10)
            places_response.raise_for_status()
            places_data = places_response.json()
            
            status = places_data.get('status')
            if status == 'OK' and places_data.get('results'):
                pois_found = places_data['results']
                print(f"   ✓ Found {len(pois_found)} POIs within {radius}m")
                break
            elif status == 'ZERO_RESULTS':
                print(f"   ○ No POIs within {radius}m")
                continue
            elif status == 'REQUEST_DENIED':
                print(f"   ✗ Places API access denied: {places_data.get('error_message', 'Unknown error')}")
                print(f"      (Check if Places API is enabled in Google Cloud Console)")
                break
            else:
                print(f"   ⚠ Places API status: {status} at {radius}m")
                if places_data.get('error_message'):
                    print(f"      Error: {places_data['error_message']}")
        except Exception as e:
            print(f"   ✗ Places API error at {radius}m: {e}")
            continue
    
    if pois_found:
        try:
            # Debug: Show ALL POIs found, not just the first
            print(f"   📋 All {len(pois_found)} POIs found:")
            for i, poi in enumerate(pois_found, 1):
                poi_types = poi.get('types', [])
                print(f"      {i}. {poi.get('name')} - Types: {', '.join(poi_types[:3])}")
            
            # Filter out administrative areas (locality, political) - we want actual businesses
            excluded_types = {'locality', 'political', 'administrative_area_level_1', 
                            'administrative_area_level_2', 'administrative_area_level_3',
                            'country', 'postal_code'}
            
            actual_business = None
            for poi in pois_found:
                poi_types = set(poi.get('types', []))
                # Check if this is NOT just an administrative boundary
                if not poi_types.issubset(excluded_types) and poi_types - excluded_types:
                    actual_business = poi
                    print(f"   ✓ Selected business: {poi.get('name')} (types: {', '.join(list(poi_types)[:3])})")
                    break
            
            # Use the actual business if found, otherwise fall back to first result
            place = actual_business if actual_business else pois_found[0]
            if not actual_business:
                print(f"   ⚠ No actual business found, using: {place.get('name')}")
            
            # Get detailed info for this place
            place_id = place.get('place_id')
            details_url = "https://maps.googleapis.com/maps/api/place/details/json"
            details_params = {
                'place_id': place_id,
                'fields': 'name,formatted_address,address_components,types,geometry,rating,user_ratings_total,vicinity',
                'key': api_key
            }
            
            details_response = requests.get(details_url, params=details_params, timeout=10)
            details_response.raise_for_status()
            details_data = details_response.json()
            
            if details_data.get('status') == 'OK':
                result = details_data['result']
                
                address_components = {comp['types'][0]: comp['long_name'] 
                                     for comp in result.get('address_components', [])}
                
                return {
                    'display_name': result.get('formatted_address', ''),
                    'name': result.get('name'),
                    'vicinity': result.get('vicinity'),
                    'address': {
                        'road': address_components.get('route'),
                        'house_number': address_components.get('street_number'),
                        'suburb': address_components.get('sublocality') or address_components.get('neighborhood'),
                        'city': address_components.get('locality'),
                        'state': address_components.get('administrative_area_level_1'),
                        'postcode': address_components.get('postal_code'),
                        'country': address_components.get('country')
                    },
                    'types': result.get('types', []),
                    'place_id': place_id,
                    'geometry': result.get('geometry'),
                    'rating': result.get('rating'),
                    'user_ratings_total': result.get('user_ratings_total'),
                    'poi_found': True
                }
        except Exception as e:
            print(f"   (Places API error: {e}, falling back to geocoding)")
    
    # Fallback to regular geocoding if no POI found
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        'latlng': f"{lat},{lon}",
        'key': api_key,
        'result_type': 'street_address|premise|subpremise'
    }
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    if data.get('status') != 'OK' or not data.get('results'):
        return {'error': f"Google API status: {data.get('status', 'UNKNOWN')}"}
    
    result = data['results'][0]
    address_components = {comp['types'][0]: comp['long_name'] 
                         for comp in result.get('address_components', [])}
    
    return {
        'display_name': result.get('formatted_address', ''),
        'address': {
            'road': address_components.get('route'),
            'house_number': address_components.get('street_number'),
            'suburb': address_components.get('sublocality') or address_components.get('neighborhood'),
            'city': address_components.get('locality'),
            'state': address_components.get('administrative_area_level_1'),
            'postcode': address_components.get('postal_code'),
            'country': address_components.get('country')
        },
        'types': result.get('types', []),
        'place_id': result.get('place_id'),
        'geometry': result.get('geometry'),
        'poi_found': False
    }


def aws_location_lookup(lat: float, lon: float, index_name: str = None) -> dict:
    """AWS Location Service (Places API with comprehensive POI data)"""
    if not HAS_BOTO3:
        return {'error': 'boto3 not installed - run: pip install boto3'}
    
    try:
        # Initialize AWS Location client
        client = boto3.client('location')
        
        # Use default place index if not specified
        if not index_name:
            # List available place indexes
            try:
                indexes = client.list_place_indexes()
                if indexes.get('Entries'):
                    index_name = indexes['Entries'][0]['IndexName']
                    print(f"   ℹ Using place index: {index_name}")
                else:
                    return {'error': 'No AWS Location Place Indexes found. Create one in AWS Console.'}
            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == 'AccessDeniedException':
                    return {'error': 'AWS IAM permissions missing. Add policy: geo:ListPlaceIndexes, geo:SearchPlaceIndexForPosition'}
                else:
                    return {'error': f'Cannot list place indexes: {e.response["Error"]["Message"]}'}
            except Exception as e:
                return {'error': f'AWS error: {e}'}
        
        # Search for places near coordinates
        pois_found = []
        for max_results in [10, 20, 50]:
            try:
                response = client.search_place_index_for_position(
                    IndexName=index_name,
                    Position=[lon, lat],  # AWS uses [lon, lat] order
                    MaxResults=max_results
                )
                
                results = response.get('Results', [])
                if results:
                    print(f"   ✓ Found {len(results)} results")
                    
                    # Filter for actual POIs (not just addresses)
                    for result in results:
                        place = result.get('Place', {})
                        categories = place.get('Categories', [])
                        
                        # Look for POI categories (restaurant, shop, etc)
                        poi_categories = [c for c in categories if c not in ['AddressOnly', 'Street']]
                        if poi_categories:
                            pois_found.append(place)
                    
                    if pois_found:
                        print(f"   ✓ Found {len(pois_found)} POIs")
                        break
                    else:
                        print(f"   ○ Results are addresses only, no POIs")
            except Exception as e:
                print(f"   ✗ Search error: {e}")
                continue
        
        if pois_found:
            # Use the first POI found
            place = pois_found[0]
            
            return {
                'display_name': place.get('Label', ''),
                'name': place.get('Label', '').split(',')[0] if place.get('Label') else 'Unknown',
                'address': {
                    'house_number': place.get('AddressNumber'),
                    'road': place.get('Street'),
                    'suburb': place.get('Neighborhood'),
                    'city': place.get('Municipality'),
                    'state': place.get('Region'),
                    'postcode': place.get('PostalCode'),
                    'country': place.get('Country')
                },
                'types': place.get('Categories', []),
                'geometry': {
                    'location': {
                        'lat': place.get('Geometry', {}).get('Point', [None, None])[1],
                        'lng': place.get('Geometry', {}).get('Point', [None, None])[0]
                    }
                },
                'poi_found': True
            }
        
        # Fallback: return first result even if not a POI
        response = client.search_place_index_for_position(
            IndexName=index_name,
            Position=[lon, lat],
            MaxResults=1
        )
        
        if response.get('Results'):
            place = response['Results'][0].get('Place', {})
            return {
                'display_name': place.get('Label', ''),
                'address': {
                    'road': place.get('Street'),
                    'city': place.get('Municipality'),
                    'state': place.get('Region'),
                    'postcode': place.get('PostalCode'),
                    'country': place.get('Country')
                },
                'types': place.get('Categories', []),
                'poi_found': False
            }
        
        return {'error': 'No results from AWS Location Service'}
        
    except NoCredentialsError:
        return {'error': 'AWS credentials not configured. Run: aws configure'}
    except ClientError as e:
        return {'error': f'AWS error: {e.response["Error"]["Message"]}'}
    except Exception as e:
        return {'error': f'AWS Location error: {e}'}


def format_result(provider: str, data: dict) -> str:
    """Format geocoding result for display."""
    if 'error' in data:
        return f"❌ {data['error']}"
    
    lines = []
    
    # POI indicator
    if data.get('poi_found'):
        lines.append("✨ POI FOUND (actual place/business)")
    
    # Name (POI name if available)
    name = data.get('name')
    if name:
        lines.append(f"🏢 POI Name: {name}")
        
        # Rating if available
        rating = data.get('rating')
        if rating:
            total = data.get('user_ratings_total', 0)
            lines.append(f"   ⭐ Rating: {rating}/5 ({total} reviews)")
    
    # Vicinity (short address for POI)
    vicinity = data.get('vicinity')
    if vicinity:
        lines.append(f"📍 Vicinity: {vicinity}")
    
    # Display name / formatted address
    display_name = data.get('display_name', 'N/A')
    lines.append(f"📫 Full Address: {display_name}")
    
    # Address components
    address = data.get('address', {})
    if address:
        parts = []
        for key in ['house_number', 'road', 'suburb', 'city', 'state', 'postcode']:
            if address.get(key):
                parts.append(f"{key}: {address[key]}")
        if parts:
            lines.append(f"   Components: {' | '.join(parts)}")
    
    # Type/Category
    types = data.get('types', [])
    if types:
        # Highlight relevant types
        relevant_types = [t for t in types if t not in ['political', 'geocode']][:3]
        if relevant_types:
            lines.append(f"   🏷️  Categories: {', '.join(relevant_types)}")
    else:
        osm_type = data.get('type', data.get('osm_type'))
        if osm_type:
            lines.append(f"   Type: {osm_type}")
    
    return '\n'.join(lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 compare_geocoding.py <latitude> <longitude>")
        return 1
    
    lat = float(sys.argv[1])
    lon = float(sys.argv[2])
    
    print("=" * 80)
    print(f"COMPARING GEOCODING SERVICES")
    print("=" * 80)
    print(f"\n📍 Coordinates: {lat}, {lon}")
    print(f"🗺️  Google Maps: https://www.google.com/maps?q={lat},{lon}")
    print()
    
    # Test providers
    providers = {
        'Nominatim (OSM)': lambda: nominatim_lookup(lat, lon),
        'Photon (Komoot)': lambda: photon_lookup(lat, lon),
    }
    
    # Check for API keys in env or .env file
    import os
    from pathlib import Path
    
    # Try to load from .env file
    env_file = Path('.env')
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())
    
    locationiq_key = os.environ.get('LOCATIONIQ_API_KEY')
    google_key = os.environ.get('GOOGLE_MAPS_API_KEY')
    aws_index = os.environ.get('AWS_LOCATION_INDEX_NAME')  # Optional, will auto-detect if not set
    
    if google_key:
        providers['Google Maps'] = lambda: google_maps_lookup(lat, lon, google_key)
    
    if locationiq_key:
        providers['LocationIQ'] = lambda: locationiq_lookup(lat, lon, locationiq_key)
    
    # Add AWS Location Service if boto3 is available
    if HAS_BOTO3:
        providers['AWS Location'] = lambda: aws_location_lookup(lat, lon, aws_index)
    
    results = {}
    
    for provider_name, lookup_func in providers.items():
        print(f"\n{'─' * 80}")
        print(f"🔍 {provider_name}")
        print('─' * 80)
        
        try:
            data = lookup_func()
            results[provider_name] = data
            print(format_result(provider_name, data))
        except Exception as e:
            print(f"❌ Error: {e}")
            results[provider_name] = {'error': str(e)}
    
    print("\n" + "=" * 80)
    print("COMPARISON COMPLETE")
    print("=" * 80)
    
    # Summary
    print("\n📊 SUMMARY:")
    print("\n🔹 Nominatim (OSM): Free, current provider - often returns broad area names")
    print("🔹 Photon (Komoot): Free, OSM-based - sometimes better POI accuracy")
    print("🔹 Google Maps: Most accurate for POIs/businesses - commercial grade")
    print("🔹 LocationIQ: Enhanced Nominatim - 15k free requests/day")
    if HAS_BOTO3:
        print("🔹 AWS Location: Enterprise-grade POI data - requires AWS account")
    print("\n💡 RECOMMENDATION:")
    print("Based on results above, choose the provider with:")
    print("  ✓ Most specific POI name (restaurant, business)")
    print("  ✓ Correct street address (not mountain/neighborhood)")
    print("  ✓ Best balance of accuracy vs cost/rate limits")
    print("\nGoogle Maps is typically most accurate for commercial locations.")
    print("AWS Location is excellent for enterprise use with comprehensive POI data.")
    print("Photon/LocationIQ are good free alternatives if Google/AWS usage is too high.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
