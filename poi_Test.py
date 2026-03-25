import os
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("Missing GOOGLE_API_KEY in environment variables")


def reverse_geocode(lat, lon):
    url = (
        "https://maps.googleapis.com/maps/api/geocode/json"
        f"?latlng={lat},{lon}&key={GOOGLE_API_KEY}"
    )
    r = requests.get(url).json()
    if r["status"] == "OK":
        return r["results"][0]["formatted_address"]
    return None


def nearby_poi(lat, lon, radius=50):
    url = (
        "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        f"?location={lat},{lon}&radius={radius}&key={GOOGLE_API_KEY}"
    )
    r = requests.get(url).json()

    if r["status"] == "OK" and len(r["results"]) > 0:
        top = r["results"][0]
        return {
            "name": top.get("name"),
            "types": top.get("types"),
            "vicinity": top.get("vicinity")
        }
    return None


def textsearch_poi(lat, lon):
    url = (
        "https://maps.googleapis.com/maps/api/place/textsearch/json"
        f"?query=restaurant&location={lat},{lon}&radius=100&key={GOOGLE_API_KEY}"
    )
    r = requests.get(url).json()

    if r["status"] == "OK" and len(r["results"]) > 0:
        top = r["results"][0]
        return {
            "name": top.get("name"),
            "types": top.get("types"),
            "formatted_address": top.get("formatted_address")
        }
    return None


def get_location_info(lat, lon):
    address = reverse_geocode(lat, lon)

    # First try nearby search
    poi = nearby_poi(lat, lon)

    # If nearby search fails or returns a route, fall back to text search
    if not poi or poi["types"] == ["route"]:
        poi = textsearch_poi(lat, lon)

    return {
        "address": address,
        "poi": poi
    }


# Example usage:
lat = 49.88151111111111
lon = -119.4345388888889

info = get_location_info(lat, lon)
print(info)