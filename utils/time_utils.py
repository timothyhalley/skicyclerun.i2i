from datetime import datetime, UTC
from typing import Optional, Union
from zoneinfo import ZoneInfo


def utc_now_iso_z() -> str:
    """Return current UTC time in ISO8601 format with trailing 'Z'.
    Example: '2025-11-14T17:59:30.123456Z'
    """
    # Keep microseconds; normalize +00:00 suffix to 'Z'
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_any_datetime(value: Union[str, datetime]) -> Optional[datetime]:
    """Parse a datetime from various inputs.
    Accepts ISO8601 strings (with or without Z), EXIF-style 'YYYY:MM:DD HH:MM:SS', or datetime objects.
    Returns naive or aware datetime depending on source; None if unparseable.
    """
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    s = value.strip()
    # Try ISO8601
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        pass
    # Try EXIF style
    try:
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def infer_utc_from_local_naive(date_value: Union[str, datetime], lat: float, lon: float) -> Optional[str]:
    """Infer UTC ISO8601 'Z' time from a local naive datetime and GPS coordinates.

    - Determines timezone from lat/lon using timezonefinder (if installed).
    - Interprets the provided datetime as local time in that zone (if naive).
    - Converts to UTC and returns ISO string with trailing 'Z'.

    Returns None if inference is not possible (e.g., no timezone found or parser errors).
    """
    try:
        from timezonefinder import TimezoneFinder  # type: ignore
    except Exception:
        return None

    dt = _parse_any_datetime(date_value)
    if dt is None:
        return None

    tf = TimezoneFinder()
    tzname = tf.timezone_at(lng=float(lon), lat=float(lat)) or tf.closest_timezone_at(lng=float(lon), lat=float(lat))
    if not tzname:
        return None

    try:
        tz = ZoneInfo(tzname)
        # Treat naive as local time in the found timezone
        if dt.tzinfo is None:
            local_dt = dt.replace(tzinfo=tz)
        else:
            local_dt = dt.astimezone(tz)
        utc_dt = local_dt.astimezone(UTC)
        return utc_dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return None
