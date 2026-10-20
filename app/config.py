"""Settings for the Bus Tracker. Every value can be changed with an environment variable."""

import json
import os
from dataclasses import dataclass


def _number(name, default, cast):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


def _headers(name):
    """A JSON object such as {"x-api-key": "abc"}, turned into a tuple of (name, value) pairs."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except ValueError:
        return ()
    if not isinstance(data, dict):
        return ()
    return tuple((str(k), str(v)) for k, v in data.items())


def _center(name, default):
    raw = os.environ.get(name, "")
    try:
        lat, lon = (float(p) for p in raw.split(","))
    except ValueError:
        return default
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return default


@dataclass(frozen=True)
class Settings:
    # The transit agency's live vehicle feed (GTFS-Realtime). Leave empty to run in demo mode.
    feed_url: str = ""
    feed_headers: tuple = ()  # extra request headers, for agencies that want an API key header
    agency_name: str = ""
    feed_refresh_seconds: float = 10.0  # never ask the agency more often than this
    feed_timeout: float = 8.0
    feed_max_bytes: int = 8_000_000
    vehicle_max_age: int = 300  # hide buses whose last position is older than this many seconds
    # The map.
    center_lat: float = 40.7580
    center_lon: float = -73.9855
    zoom: float = 12.0
    tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    tile_attribution: str = "© OpenStreetMap contributors"
    # Riders who share their location.
    rider_ttl: int = 120  # a rider who has been silent this long is dropped
    rider_move_window: int = 180  # a rider who has not moved for this long is hidden
    rider_move_meters: float = 50.0  # how far a rider must travel to count as moving
    rider_min_interval: float = 3.0  # shortest gap between two reports from one rider
    rider_max_accuracy: float = 100.0  # ignore positions less accurate than this, in meters
    rider_max_speed: float = 35.0  # faster than this (m/s, about 125 km/h) is not a city bus
    rider_cluster_meters: float = 100.0  # riders this close on one route are on the same bus
    max_riders: int = 2000
    max_riders_per_visitor: int = 5
    # Limits per visitor.
    rate_limit_reports: int = 60  # rider position reports per window
    rate_limit_report_window: int = 60
    rate_limit_starts: int = 10  # times a visitor may start sharing per window
    rate_limit_start_window: int = 600
    rate_limit_reads: int = 30  # map refreshes per window
    rate_limit_read_window: int = 60
    trusted_proxy_hops: int = 1  # proxies in front of the app (Railway adds one)

    @classmethod
    def from_env(cls):
        d = cls()
        lat, lon = _center("MAP_CENTER", (d.center_lat, d.center_lon))
        return cls(
            feed_url=os.environ.get("FEED_URL", "").strip(),
            feed_headers=_headers("FEED_HEADERS"),
            agency_name=os.environ.get("AGENCY_NAME", "").strip()[:80],
            feed_refresh_seconds=max(5.0, _number("FEED_REFRESH_SECONDS", d.feed_refresh_seconds, float)),
            center_lat=lat,
            center_lon=lon,
            zoom=min(18.0, max(2.0, _number("MAP_ZOOM", d.zoom, float))),
            tile_url=os.environ.get("TILE_URL", "").strip() or d.tile_url,
            tile_attribution=os.environ.get("TILE_ATTRIBUTION", "").strip() or d.tile_attribution,
            trusted_proxy_hops=_number("TRUSTED_PROXY_HOPS", d.trusted_proxy_hops, int),
        )
