"""Small helpers for latitude and longitude."""

import math

EARTH_RADIUS_M = 6_371_000.0


def is_valid_position(lat, lon):
    return (
        isinstance(lat, (int, float))
        and isinstance(lon, (int, float))
        and not isinstance(lat, bool)
        and not isinstance(lon, bool)
        and math.isfinite(lat)
        and math.isfinite(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    )


def distance_m(lat1, lon1, lat2, lon2):
    """Distance in meters between two points, along the surface of the earth."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Compass direction from the first point to the second: 0 is north, 90 is east."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
