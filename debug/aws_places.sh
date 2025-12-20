#!/bin/bash
#
# AWS Location Service Place Search
# Usage: ./debug/aws_places.sh --lat <latitude> --lon <longitude> [--text "search text"]
#

# Default values
LAT=""
LON=""
TEXT="landmark"
INDEX_NAME="explore.place.Esri"
MAX_RESULTS=5

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
    --text)
      TEXT="$2"
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
      echo "Usage: $0 --lat <latitude> --lon <longitude> [--text \"search text\"] [--index MyPlaceIndex] [--max-results 5]"
      exit 1
      ;;
  esac
done

# Validate required arguments
if [[ -z "$LAT" ]] || [[ -z "$LON" ]]; then
  echo "Error: --lat and --lon are required"
  echo "Usage: $0 --lat <latitude> --lon <longitude> [--text \"search text\"]"
  echo ""
  echo "Example:"
  echo "  $0 --lat -37.81037222222222 --lon 144.96310555555556"
  echo "  $0 --lat -37.81037222222222 --lon 144.96310555555556 --text \"historic clock\""
  exit 1
fi

# Note: AWS bias-position format is: longitude,latitude (reversed order!)
echo "🔍 Searching AWS Location Service..."
echo "   Latitude:  $LAT"
echo "   Longitude: $LON"
echo "   Text:      $TEXT"
echo "   Index:     $INDEX_NAME"
echo "   Max:       $MAX_RESULTS"
echo ""

aws location search-place-index-for-text \
  --index-name "$INDEX_NAME" \
  --text "$TEXT" \
  --bias-position "$LON" "$LAT" \
  --max-results "$MAX_RESULTS"
