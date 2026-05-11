"""EXIF GPS extraction from image files."""
from typing import Optional, Tuple

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS


def _normalize_exif_text(value) -> Optional[str]:
    """Normalize EXIF/IPTC text and repair common mojibake artifacts."""
    raw = value
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")

    text = str(raw).strip().strip("\x00")
    if not text:
        return None

    # Apple Photos exports can occasionally surface UTF-8 text as latin1-like
    # mojibake (e.g., "MÃ©dano", "communityâdriven"). Repair when detected.
    if any(ch in text for ch in ("Ã", "â", "Â")):
        try:
            repaired = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore").strip()
            if repaired:
                before_noise = sum(text.count(ch) for ch in ("Ã", "â", "Â"))
                after_noise = sum(repaired.count(ch) for ch in ("Ã", "â", "Â"))
                if after_noise <= before_noise:
                    text = repaired
        except Exception:
            pass

    return text or None


def get_exif_author_note(image_path: str) -> Optional[str]:
    """Return the author narrative note embedded in image EXIF/IPTC fields.

    Checks EXIF ``ImageDescription`` first, then ``UserComment``.  Returns the
    first non-empty value found, or ``None`` if neither field is set.

    Photographers can set this note in any standard tool (Apple Photos caption,
    Lightroom description field, ``exiftool -ImageDescription="..."``) before
    running the pipeline.  The pipeline stores it as ``author_note`` in
    master.json and passes it through to the travel-story RAG payload so the
    LLM can use it as authoritative first-person context.
    """
    try:
        with Image.open(image_path) as img:
            exif = img._getexif()
            if not exif:
                return None

            image_description: Optional[str] = None
            user_comment: Optional[str] = None

            for tag, value in exif.items():
                tag_name = TAGS.get(tag, "")
                if tag_name == "ImageDescription":
                    cleaned = _normalize_exif_text(value)
                    if cleaned:
                        image_description = cleaned
                elif tag_name == "UserComment":
                    raw = value
                    if isinstance(raw, bytes):
                        # EXIF UserComment has an 8-byte charset header
                        raw = raw[8:].decode("utf-8", errors="ignore")
                    cleaned = _normalize_exif_text(raw)
                    if cleaned:
                        user_comment = cleaned

            return image_description or user_comment or None
    except Exception:
        return None


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
