#!/bin/bash
#
# AWS Location Service - Search for places near a GPS position
# Usage: ./debug/aws_nearby.sh --lat <latitude> --lon <longitude>
#

# Default values
LAT=""
LON=""
INDEX_NAME="explore.place.Esri"
MAX_RESULTS=10

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
    --index)
      INDEX_NAME="$2"
      shift 2
      ;;
    --max-results)
      MAX_RESULTS="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 --lat <latitude> --lon <longitude> [--index MyPlaceIndex] [--max-results 10]"
      exit 1
      ;;
  esac
done

# Validate required arguments
if [[ -z "$LAT" ]] || [[ -z "$LON" ]]; then
  echo "Error: --lat and --lon are required"
  echo "Usage: $0 --lat <latitude> --lon <longitude>"
  echo ""
  echo "Example:"
  echo "  $0 --lat -37.81037222222222 --lon 144.96310555555556"
  exit 1
fi

# Note: AWS position format is: longitude,latitude (reversed order!)
echo "🔍 Searching nearby places at GPS position..."
echo "   Latitude:  $LAT"
echo "   Longitude: $LON"
echo "   Index:     $INDEX_NAME"
echo "   Max:       $MAX_RESULTS"
echo ""

aws location search-place-index-for-position \
  --index-name "$INDEX_NAME" \
  --position "$LON" "$LAT" \
  --max-results "$MAX_RESULTS"
