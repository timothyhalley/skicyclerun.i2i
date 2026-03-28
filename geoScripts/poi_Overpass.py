import requests
import math

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def query_osm(query):
    response = requests.post(OVERPASS_URL, data={"data": query})
    return response.json().get("elements", [])

def find_features(lat, lon, radius=500):
    q = f"""
    [out:json];

    (
      // Trails
      way(around:{radius},{lat},{lon})["highway"="path"]["name"];
      way(around:{radius},{lat},{lon})["highway"="footway"]["name"];

      // Parks / protected areas
      relation(around:{radius},{lat},{lon})["leisure"="park"]["name"];
      relation(around:{radius},{lat},{lon})["boundary"="protected_area"]["name"];

      // Mountains / peaks
      node(around:{radius},{lat},{lon})["natural"="peak"]["name"];

      // Natural features (lakes, beaches, etc.)
      node(around:{radius},{lat},{lon})["natural"]["name"];
      way(around:{radius},{lat},{lon})["natural"]["name"];
    );

    out center;
    """

    results = query_osm(q)

    features = []
    for el in results:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        # Determine coordinates
        if "lat" in el and "lon" in el:
            lat2, lon2 = el["lat"], el["lon"]
        else:
            lat2, lon2 = el["center"]["lat"], el["center"]["lon"]

        dist = haversine(lat, lon, lat2, lon2)

        features.append({
            "name": name,
            "type": tags.get("highway") or tags.get("leisure") or tags.get("natural") or tags.get("boundary"),
            "distance_m": dist,
            "tags": tags
        })

    return sorted(features, key=lambda x: x["distance_m"])


def get_location_context(lat, lon):
    features = find_features(lat, lon)

    context = {
        "trail": None,
        "park": None,
        "mountain": None,
        "natural_feature": None
    }

    for f in features:
        t = f["type"]

        if t in ("path", "footway") and context["trail"] is None:
            context["trail"] = f

        if t in ("park", "protected_area") and context["park"] is None:
            context["park"] = f

        if t == "peak" and context["mountain"] is None:
            context["mountain"] = f

        if t in ("beach", "water", "wood", "scrub", "ridge", "cliff") and context["natural_feature"] is None:
            context["natural_feature"] = f

    return context


# Example usage:
# The Keg
# lat = 49.88151111111111
# lon = -119.4345388888889

# Knox Mountain Park
# lat = 49.91974166666667
# lon = -119.47923333333334

# Water Street
# lat = 49.89121111111111
# lon = -119.49793333333334

# Darrell's Place
lat = 49.862775
lon = -119.46897777777778

context = get_location_context(lat, lon)
print(context)

