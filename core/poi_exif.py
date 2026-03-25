"""EXIF GPS extraction from image files."""
from typing import Optional, Tuple

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS


def _convert_to_degrees(value) -> float:
    """Convert an EXIF GPS coordinate tuple to decimal degrees.

    Handles both the old tuple format and modern Pillow IFDRational objects.
    """
    def to_float(x) -> float:
        try:
            return float(x)
        except Exception:
            return float(x[0]) / float(x[1])

    d, m, s = value
    return to_float(d) + to_float(m) / 60.0 + to_float(s) / 3600.0


def get_exif_gps(image_path: str) -> Optional[Tuple[float, float]]:
    """Return ``(lat, lon)`` in decimal degrees from image EXIF, or ``None``."""
    try:
        with Image.open(image_path) as img:
            exif = img._getexif()
            if not exif:
                return None

            gps_info: dict = {}
            for tag, val in exif.items():
                if TAGS.get(tag) == "GPSInfo":
                    for sub_tag in val:
                        gps_info[GPSTAGS.get(sub_tag)] = val[sub_tag]

            if not gps_info:
                return None

            lat = gps_info.get("GPSLatitude")
            lat_ref = gps_info.get("GPSLatitudeRef")
            lon = gps_info.get("GPSLongitude")
            lon_ref = gps_info.get("GPSLongitudeRef")

            if not lat or not lon or not lat_ref or not lon_ref:
                return None

            lat_deg = _convert_to_degrees(lat)
            lon_deg = _convert_to_degrees(lon)

            if lat_ref != "N":
                lat_deg = -lat_deg
            if lon_ref != "E":
                lon_deg = -lon_deg

            return lat_deg, lon_deg
    except Exception:
        return None
