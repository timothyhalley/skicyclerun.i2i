#!/usr/bin/env python3
"""
Test POI discovery for any image
Testing different radius, FOV, and category settings
"""
import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.geo_extractor import GeoExtractor

# Parse arguments
parser = argparse.ArgumentParser(description='Test POI discovery for an image')
parser.add_argument('--image', required=True, help='Path to the image file')
args = parser.parse_args()

# Load config
with open('config/pipeline_config.json', 'r') as f:
    config = json.load(f)

# Load master.json to get image metadata
master_path = Path(config.get('library_root', '/Volumes/MySSD/skicyclerun.i2i')) / 'pipeline/metadata/master.json'
with open(master_path, 'r') as f:
    master = json.load(f)

# Find image in master.json
image_path = str(Path(args.image).resolve())
if image_path not in master:
    print(f"❌ ERROR: Image not found in master.json: {image_path}")
    print(f"\nAvailable images:")
    for img in master.keys():
        print(f"  {img}")
    sys.exit(1)

image_data = master[image_path]

# Extract coordinates and heading
if 'gps' not in image_data:
    print(f"❌ ERROR: No GPS data found for image: {image_path}")
    sys.exit(1)

lat = image_data['gps']['lat']
lon = image_data['gps']['lon']
heading = image_data['gps'].get('heading', None)

print("=" * 80)
print("POI DISCOVERY TEST")
print("=" * 80)
print(f"Image: {Path(image_path).name}")
print(f"Location: {image_data['location'].get('display_name', 'Unknown')}")
print(f"Coordinates: {lat}, {lon}")
print(f"Heading: {heading}° ({image_data['gps'].get('cardinal', 'N/A')})" if heading else "Heading: N/A")
print()

# Test 1: Current settings (60° FOV, 500m max distance)
print("-" * 80)
print("TEST 1: Current settings (60° FOV, 500m max, categories: museum/attraction/viewpoint/historic/natural)")
print("-" * 80)
extractor1 = GeoExtractor(config)
pois1 = extractor1.fetch_pois(lat, lon, heading_deg=heading)
print(f"Found {len(pois1)} POIs")
for poi in pois1:
    print(f"  - {poi['name']} ({poi['category']}) - {poi['distance_m']}m @ {poi['bearing_cardinal']}, score: {poi['score']}")
print()

# Test 2: Wider FOV (120°)
print("-" * 80)
print("TEST 2: Wider FOV (120°, same distance/categories)")
print("-" * 80)
config2 = json.loads(json.dumps(config))
config2['metadata_extraction']['poi_enrichment']['fov_degrees'] = 120
extractor2 = GeoExtractor(config2)
pois2 = extractor2.fetch_pois(lat, lon, heading_deg=heading)
print(f"Found {len(pois2)} POIs")
for poi in pois2:
    print(f"  - {poi['name']} ({poi['category']}) - {poi['distance_m']}m @ {poi['bearing_cardinal']}, score: {poi['score']}")
print()

# Test 3: No heading filter
print("-" * 80)
print("TEST 3: No heading filter (360° search, same distance/categories)")
print("-" * 80)
config3 = json.loads(json.dumps(config))
config3['metadata_extraction']['poi_enrichment']['use_heading_filter'] = False
extractor3 = GeoExtractor(config3)
pois3 = extractor3.fetch_pois(lat, lon, heading_deg=heading)
print(f"Found {len(pois3)} POIs")
for poi in pois3:
    print(f"  - {poi['name']} ({poi['category']}) - {poi['distance_m']}m @ {poi['bearing_cardinal']}, score: {poi['score']}")
print()

# Test 4: Longer distance (800m)
print("-" * 80)
print("TEST 4: Longer distance (800m, 120° FOV, same categories)")
print("-" * 80)
config4 = json.loads(json.dumps(config))
config4['metadata_extraction']['poi_enrichment']['fov_degrees'] = 120
config4['metadata_extraction']['poi_enrichment']['max_distance_m'] = 800
extractor4 = GeoExtractor(config4)
pois4 = extractor4.fetch_pois(lat, lon, heading_deg=heading)
print(f"Found {len(pois4)} POIs")
for poi in pois4:
    print(f"  - {poi['name']} ({poi['category']}) - {poi['distance_m']}m @ {poi['bearing_cardinal']}, score: {poi['score']}")
print()

# Test 5: Enhanced query with amenity/leisure/streets (360° search)
print("-" * 80)
print("TEST 5: Enhanced Overpass query (amenity/leisure/named streets, 360° search)")
print("-" * 80)
# Custom query with expanded categories
import requests
radius = 600
timeout = 25
overpass_url = "https://overpass-api.de/api/interpreter"
user_agent = "skicyclerun-pipeline/1.0"

enhanced_query = f"""
[out:json][timeout:{timeout}];
(
  node(around:{radius},{lat},{lon})["tourism"~"^(attraction|museum|viewpoint)$"]["name"]; 
  node(around:{radius},{lat},{lon})["historic"]["name"]; 
  node(around:{radius},{lat},{lon})["natural"]["name"];
  node(around:{radius},{lat},{lon})["amenity"~"^(bar|pub|restaurant|cafe|nightclub|theatre)$"]["name"];
  node(around:{radius},{lat},{lon})["leisure"]["name"];
  way(around:{radius},{lat},{lon})["highway"~"^(pedestrian|footway)$"]["name"];
);
out body 50;
"""

try:
    r = requests.post(overpass_url, data={'data': enhanced_query}, headers={'User-Agent': user_agent}, timeout=timeout)
    if r.status_code == 200:
        out = r.json()
        elements = out.get('elements', [])
        enhanced_pois = []
        for el in elements:
            tags = el.get('tags', {})
            name = tags.get('name')
            if not name:
                continue
            
            # Get lat/lon (for ways, use center or first node)
            if el['type'] == 'node':
                plat, plon = el.get('lat'), el.get('lon')
            elif el['type'] == 'way' and 'center' in el:
                plat, plon = el['center']['lat'], el['center']['lon']
            else:
                continue
            
            # Calculate distance
            import math
            R = 6371000.0
            phi1, phi2 = math.radians(lat), math.radians(plat)
            dphi = math.radians(plat - lat)
            dlambda = math.radians(plon - lon)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            distance = R * c
            
            # Calculate bearing
            y = math.sin(dlambda) * math.cos(phi2)
            x = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlambda)
            bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
            
            # Determine category
            cat = tags.get('tourism') or tags.get('amenity') or tags.get('leisure') or \
                  ('historic' if 'historic' in tags else tags.get('natural')) or \
                  ('street' if 'highway' in tags else 'unknown')
            
            enhanced_pois.append({
                'name': name,
                'category': cat,
                'distance_m': int(distance),
                'type': el['type']
            })
        
        # Sort by distance
        enhanced_pois.sort(key=lambda x: x['distance_m'])
        
        print(f"Found {len(enhanced_pois)} POIs (including streets, bars, restaurants)")
        for poi in enhanced_pois[:20]:  # Show top 20
            print(f"  - {poi['name']} ({poi['category']}, {poi['type']}) - {poi['distance_m']}m")
    else:
        print(f"Error: HTTP {r.status_code}")
except Exception as e:
    print(f"Error: {e}")
print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Test 1 (current - 60° FOV, 500m): {len(pois1)} POIs")
print(f"Test 2 (120° FOV): {len(pois2)} POIs")
print(f"Test 3 (360° search): {len(pois3)} POIs")
print(f"Test 4 (800m distance): {len(pois4)} POIs")
print()
print("Note: Test 5 shows enhanced query results above with streets, bars, and restaurants")
