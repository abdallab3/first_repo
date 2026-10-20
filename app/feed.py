"""Where bus positions come from: a transit agency's live feed, or simulated buses for a demo."""

import math
import threading
import time

import requests

from .geo import bearing_deg, distance_m
from .gtfsrt import FeedError, parse_vehicle_positions


def _bus(source, vehicle_id, route, label, lat, lon, bearing, speed, age):
    return {
        "id": f"{source}:{vehicle_id}",
        "route": route,
        "label": label,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "bearing": None if bearing is None else round(bearing) % 360,
        "speed": None if speed is None else round(speed, 1),
        "age": max(0, int(age)),
        "source": "agency",
        "riders": 0,
    }


class AgencyFeed:
    """Reads a GTFS-Realtime vehicle feed, and never asks for it more often than the setting allows."""

    mode = "live"

    def __init__(self, settings, session=None, clock=time.time):
        self.s = settings
        self.session = session or requests.Session()
        self.clock = clock
        self._lock = threading.Lock()
        self._last_try = None
        self._last_ok = None
        self._error = None
        self._vehicles = []
        self._feed_time = None

    def _fetch(self):
        headers = {"Accept": "application/x-protobuf, application/octet-stream, */*;q=0.5"}
        headers.update(dict(self.s.feed_headers))
        resp = self.session.get(self.s.feed_url, headers=headers, timeout=self.s.feed_timeout, stream=True)
        try:
            if resp.status_code != 200:
                raise FeedError(f"The agency's feed answered with an error (code {resp.status_code}).")
            chunks, total = [], 0
            for chunk in resp.iter_content(65536):
                total += len(chunk)
                if total > self.s.feed_max_bytes:
                    raise FeedError("The agency's feed is larger than this app accepts.")
                chunks.append(chunk)
            return parse_vehicle_positions(b"".join(chunks))
        finally:
            resp.close()

    def _refresh(self, now):
        self._last_try = now
        try:
            feed_time, vehicles = self._fetch()
        except FeedError as e:
            self._error = str(e)
        except requests.RequestException:
            self._error = "The agency's feed could not be reached."
        except Exception:
            self._error = "The agency's feed could not be read."
        else:
            self._feed_time, self._vehicles, self._last_ok, self._error = feed_time, vehicles, now, None

    def read(self):
        """Return (buses, status). status has: ok, updated (seconds since 1970 or None), error."""
        now = self.clock()
        with self._lock:
            if self._last_try is None or now - self._last_try >= self.s.feed_refresh_seconds:
                self._refresh(now)
            buses = []
            for v in self._vehicles:
                stamp = v.get("timestamp") or self._feed_time or self._last_ok or now
                age = now - stamp
                if age > self.s.vehicle_max_age:
                    continue
                speed = v.get("speed")
                bus = _bus("a", v["id"] or "?", v["route"], v["label"], v["lat"], v["lon"], v.get("bearing"), speed, age)
                buses.append(bus)
            status = {"ok": self._error is None, "updated": self._last_ok, "error": self._error}
            return buses, status


class DemoFeed:
    """Simulated buses on two made-up routes, so the app has something to show with no agency."""

    mode = "demo"

    def __init__(self, settings, clock=time.time):
        lat, lon = settings.center_lat, settings.center_lon
        dlat, dlon = 0.014, 0.02
        # Route A loops around a rectangle, route B runs back and forth along a line.
        self.loop = [
            (lat - dlat, lon - dlon),
            (lat - dlat, lon + dlon),
            (lat + dlat, lon + dlon),
            (lat + dlat, lon - dlon),
            (lat - dlat, lon - dlon),
        ]
        self.line = [(lat, lon - dlon * 1.3), (lat + dlat * 0.3, lon), (lat, lon + dlon * 1.3)]
        self.clock = clock
        self.speed = 7.0

    @staticmethod
    def _lengths(points):
        return [distance_m(*points[i], *points[i + 1]) for i in range(len(points) - 1)]

    def _along(self, points, meters):
        lengths = self._lengths(points)
        meters = max(0.0, meters)
        for i, seg in enumerate(lengths):
            if meters <= seg or i == len(lengths) - 1:
                f = min(1.0, meters / seg) if seg else 0.0
                (la1, lo1), (la2, lo2) = points[i], points[i + 1]
                return la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f, bearing_deg(la1, lo1, la2, lo2)
            meters -= seg
        return points[-1][0], points[-1][1], 0.0

    def read(self):
        now = self.clock()
        buses = []
        loop_len = sum(self._lengths(self.loop))
        for n in range(3):
            d = (now * self.speed + n * loop_len / 3) % loop_len
            lat, lon, brg = self._along(self.loop, d)
            buses.append(_bus("demo", f"A{n + 1}", "A", f"A{n + 1}", lat, lon, brg, self.speed, 0))
        line_len = sum(self._lengths(self.line))
        for n in range(2):
            d = (now * self.speed + n * line_len) % (2 * line_len)
            if d <= line_len:
                lat, lon, brg = self._along(self.line, d)
            else:
                lat, lon, brg = self._along(self.line[::-1], d - line_len)
            buses.append(_bus("demo", f"B{n + 1}", "B", f"B{n + 1}", lat, lon, brg, self.speed, 0))
        return buses, {"ok": True, "updated": now, "error": None}
