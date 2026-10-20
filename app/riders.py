"""Riders who choose to share their phone's location while on a bus.

Everything here is kept in memory only and forgotten within minutes. Other visitors never see a
rider, only a bus: riders on the same route who are close together are combined into one dot.
A rider who is standing still is not shown, so nobody appears on the map just for sharing from
home or from a bus stop.
"""

import hashlib
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

from .geo import bearing_deg, distance_m, is_valid_position

ROUTE_PATTERN = re.compile(r"^[\w .\-/&#]{1,40}$")


class RiderError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class Session:
    id: str
    route: str
    ip: str
    started: float
    last_report: float | None = None
    lat: float | None = None
    lon: float | None = None
    anchor: tuple | None = None
    last_moved: float | None = None
    bearing: float | None = None
    speed: float | None = None
    track: list = field(default_factory=list)


def clean_route(raw):
    if not isinstance(raw, str):
        raise RiderError("Choose the bus route you are on.")
    route = " ".join(raw.split())
    if not ROUTE_PATTERN.match(route):
        raise RiderError("Route names can use letters, numbers, spaces and . - / & # (up to 40 characters).")
    return route


class RiderStore:
    def __init__(self, settings, clock=time.time):
        self.s = settings
        self.clock = clock
        self._lock = threading.Lock()
        self._sessions = {}

    # -- housekeeping ---------------------------------------------------------------

    def _expire(self, now):
        for sid in [
            sid
            for sid, x in self._sessions.items()
            if now - (x.last_report if x.last_report is not None else x.started) > self.s.rider_ttl
        ]:
            del self._sessions[sid]

    def active_count(self):
        with self._lock:
            self._expire(self.clock())
            return len(self._sessions)

    # -- a rider's actions ----------------------------------------------------------

    def start(self, route, ip):
        route = clean_route(route)
        now = self.clock()
        with self._lock:
            self._expire(now)
            if len(self._sessions) >= self.s.max_riders:
                raise RiderError("Sharing is full right now. Please try again in a few minutes.", 503)
            if sum(1 for x in self._sessions.values() if x.ip == ip) >= self.s.max_riders_per_visitor:
                raise RiderError("This device is already sharing from several places. Stop one first.", 429)
            sid = secrets.token_urlsafe(16)
            self._sessions[sid] = Session(id=sid, route=route, ip=ip, started=now)
            return sid

    def report(self, sid, lat, lon, accuracy):
        """Record one position. Returns 'ok' or 'ignored' (a position too vague to use)."""
        if not is_valid_position(lat, lon):
            raise RiderError("That position is not valid.")
        if accuracy is not None and (
            isinstance(accuracy, bool) or not isinstance(accuracy, (int, float)) or accuracy < 0
        ):
            raise RiderError("That position is not valid.")
        now = self.clock()
        with self._lock:
            self._expire(now)
            x = self._sessions.get(sid) if isinstance(sid, str) else None
            if x is None:
                raise RiderError("Sharing has ended. Start again to keep sharing.", 404)
            if x.last_report is not None and now - x.last_report < self.s.rider_min_interval:
                raise RiderError("Slow down: positions are accepted every few seconds.", 429)
            if accuracy is not None and accuracy > self.s.rider_max_accuracy:
                x.last_report = now  # still counts as being here, so the session stays alive
                return "ignored"
            if x.lat is not None:
                gap = distance_m(x.lat, x.lon, lat, lon)
                elapsed = max(now - x.last_report, 0.001)
                if gap / elapsed > self.s.rider_max_speed and gap > 200:
                    raise RiderError("That jump is too fast to be a bus, so it was not used.")
                if gap >= 10:
                    x.bearing = bearing_deg(x.lat, x.lon, lat, lon)
                x.speed = gap / elapsed
            if x.anchor is None:
                x.anchor = (lat, lon)
            elif distance_m(*x.anchor, lat, lon) >= self.s.rider_move_meters:
                x.last_moved = now
                x.anchor = (lat, lon)
            x.lat, x.lon, x.last_report = lat, lon, now
            return "ok"

    def stop(self, sid):
        with self._lock:
            self._sessions.pop(sid, None)

    # -- what everyone else sees ----------------------------------------------------

    def buses(self):
        """One bus per group of nearby riders on the same route."""
        now = self.clock()
        with self._lock:
            self._expire(now)
            moving = [
                x
                for x in self._sessions.values()
                if x.lat is not None
                and x.last_moved is not None
                and now - x.last_moved <= self.s.rider_move_window
            ]
        by_route = {}
        for x in sorted(moving, key=lambda r: r.started):
            by_route.setdefault(x.route.lower(), []).append(x)
        buses = []
        for key, riders in by_route.items():
            clusters = []
            for x in riders:
                for c in clusters:
                    if distance_m(c["lat"], c["lon"], x.lat, x.lon) <= self.s.rider_cluster_meters:
                        c["members"].append(x)
                        c["lat"] = sum(m.lat for m in c["members"]) / len(c["members"])
                        c["lon"] = sum(m.lon for m in c["members"]) / len(c["members"])
                        break
                else:
                    clusters.append({"lat": x.lat, "lon": x.lon, "members": [x]})
            for c in clusters:
                first = c["members"][0]
                bearings = [m.bearing for m in c["members"] if m.bearing is not None]
                newest = max(m.last_report for m in c["members"])
                speeds = [m.speed for m in c["members"] if m.speed is not None]
                digest = hashlib.sha1(first.id.encode()).hexdigest()[:8]
                buses.append(
                    {
                        "id": f"r:{digest}",
                        "route": first.route,
                        "label": "",
                        "lat": round(c["lat"], 6),
                        "lon": round(c["lon"], 6),
                        "bearing": round(bearings[0]) % 360 if bearings else None,
                        "speed": round(sum(speeds) / len(speeds), 1) if speeds else None,
                        "age": max(0, int(now - newest)),
                        "source": "riders",
                        "riders": len(c["members"]),
                    }
                )
        return buses
