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


def place_from_address(address):
    url = (
        "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        f"?input={address}&inputtype=textquery"
        f"&fields=place_id,name,types,formatted_address"
        f"&key={GOOGLE_API_KEY}"
    )
    r = requests.get(url).json()
    if r["status"] == "OK" and r["candidates"]:
        return r["candidates"][0]
    return None


def get_location_info(lat, lon):
    address = reverse_geocode(lat, lon)
    poi = place_from_address(address)
    return {
        "address": address,
        "poi": poi
    }


# Example usage:
lat = 49.88151111111111
lon = -119.4345388888889

info = get_location_info(lat, lon)
print(info)