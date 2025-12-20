#!/bin/bash
#
# Compare AWS Location Service vs Overpass API POI results
# Usage: ./debug/compare_poi_sources.sh --lat <latitude> --lon <longitude>
#

# Default values
LAT=""
LON=""
RADIUS=100

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --lat)
      LAT="$2"
      shift 2
      ;;
    --lon)
      LON="$2"
      shift 2
      ;;
    --radius)
      RADIUS="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Validate required arguments
if [[ -z "$LAT" ]] || [[ -z "$LON" ]]; then
  echo "Error: --lat and --lon are required"
  echo "Usage: $0 --lat <latitude> --lon <longitude> [--radius 100]"
  exit 1
fi

echo "🔍 Comparing POI sources at GPS: $LAT, $LON (${RADIUS}m radius)"
echo ""

# 1. AWS Location Service
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  AWS LOCATION SERVICE (Esri - commercial/addresses)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
aws location search-place-index-for-position \
  --index-name explore.place.Esri \
  --position "$LON" "$LAT" \
  --max-results 5 \
  --query 'Results[*].Place.[Label, Categories[0]]' \
  --output table 2>/dev/null || echo "AWS query failed"

echo ""
echo ""

# 2. Overpass API (OpenStreetMap)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  OVERPASS API (OpenStreetMap - POIs/landmarks/historic)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

QUERY="[out:json][timeout:15];
(
  node[\"tourism\"](around:${RADIUS},${LAT},${LON});
  node[\"historic\"](around:${RADIUS},${LAT},${LON});
  node[\"amenity\"=\"clock\"](around:${RADIUS},${LAT},${LON});
  way[\"tourism\"](around:${RADIUS},${LAT},${LON});
  way[\"historic\"](around:${RADIUS},${LAT},${LON});
);
out tags;"

RESULT=$(curl -s --data-urlencode "data=$QUERY" "https://overpass-api.de/api/interpreter")

echo "$RESULT" | jq -r '.elements[] | select(.tags.name != null) | "  • \(.tags.name) (\(.tags.tourism // .tags.historic // .tags.amenity // "landmark"))"' 2>/dev/null || echo "Overpass query failed"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💡 RECOMMENDATION:"
echo "   - Use AWS for: addresses, businesses, navigation"
echo "   - Use Overpass for: landmarks, monuments, historic sites"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
