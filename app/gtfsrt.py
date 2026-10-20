"""Read bus positions from a GTFS-Realtime feed.

Transit agencies publish live vehicle positions as a "protocol buffer" file. Only a few fields
are needed, so this reads them directly instead of depending on a larger library.

The field numbers come from the public GTFS-Realtime definition (gtfs-realtime.proto).
"""

import math
import struct

MAX_DEPTH_BYTES = 64 * 1024 * 1024


class FeedError(ValueError):
    """The data is not a readable GTFS-Realtime feed."""


def _varint(buf, i):
    shift = 0
    result = 0
    while True:
        if i >= len(buf):
            raise FeedError("The feed ended in the middle of a value.")
        byte = buf[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            raise FeedError("The feed has a number that is too large.")


def _fields(buf):
    """Yield (field number, wire type, value) for each field in one message."""
    i, n = 0, len(buf)
    while i < n:
        key, i = _varint(buf, i)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 1:
            if i + 8 > n:
                raise FeedError("The feed ended in the middle of a value.")
            value, i = buf[i : i + 8], i + 8
        elif wire == 2:
            length, i = _varint(buf, i)
            if i + length > n:
                raise FeedError("The feed ended in the middle of a value.")
            value, i = buf[i : i + length], i + length
        elif wire == 5:
            if i + 4 > n:
                raise FeedError("The feed ended in the middle of a value.")
            value, i = buf[i : i + 4], i + 4
        else:
            raise FeedError("The feed uses a format this app does not read.")
        yield number, wire, value


def _float(value, wire):
    if wire != 5:
        return None
    number = struct.unpack("<f", value)[0]
    return number if math.isfinite(number) else None


def _text(value, wire):
    if wire != 2:
        return ""
    return value.decode("utf-8", errors="replace")[:80]


def _parse_trip(buf):
    trip = {"route": "", "trip": ""}
    for number, wire, value in _fields(buf):
        if number == 1:
            trip["trip"] = _text(value, wire)
        elif number == 5:
            trip["route"] = _text(value, wire)
    return trip


def _parse_position(buf):
    pos = {}
    for number, wire, value in _fields(buf):
        if number == 1:
            pos["lat"] = _float(value, wire)
        elif number == 2:
            pos["lon"] = _float(value, wire)
        elif number == 3:
            pos["bearing"] = _float(value, wire)
        elif number == 5:
            pos["speed"] = _float(value, wire)
    return pos


def _parse_descriptor(buf):
    out = {"id": "", "label": ""}
    for number, wire, value in _fields(buf):
        if number == 1:
            out["id"] = _text(value, wire)
        elif number == 2:
            out["label"] = _text(value, wire)
    return out


def _parse_vehicle(buf):
    vehicle = {"route": "", "trip": "", "id": "", "label": "", "timestamp": None}
    for number, wire, value in _fields(buf):
        if number == 1 and wire == 2:
            trip = _parse_trip(value)
            vehicle["route"], vehicle["trip"] = trip["route"], trip["trip"]
        elif number == 2 and wire == 2:
            vehicle.update(_parse_position(value))
        elif number == 5 and wire == 0:
            vehicle["timestamp"] = value
        elif number == 8 and wire == 2:
            desc = _parse_descriptor(value)
            vehicle["id"], vehicle["label"] = desc["id"], desc["label"]
    return vehicle


def parse_vehicle_positions(data):
    """Return (feed timestamp or None, list of vehicles) from the bytes of a feed.

    Each vehicle has: id, label, route, trip, lat, lon, and where the feed gives them
    bearing (degrees), speed (meters per second) and timestamp (seconds since 1970).
    Vehicles with no usable position are left out.
    """
    if len(data) > MAX_DEPTH_BYTES:
        raise FeedError("The feed is too large.")
    feed_time = None
    vehicles = []
    saw_header = False
    for number, wire, value in _fields(data):
        if number == 1 and wire == 2:
            saw_header = True
            for hn, hw, hv in _fields(value):
                if hn == 3 and hw == 0:
                    feed_time = hv
        elif number == 2 and wire == 2:
            entity_id = ""
            vehicle = None
            deleted = False
            for en, ew, ev in _fields(value):
                if en == 1:
                    entity_id = _text(ev, ew)
                elif en == 2 and ew == 0:
                    deleted = bool(ev)
                elif en == 4 and ew == 2:
                    vehicle = _parse_vehicle(ev)
            if deleted or vehicle is None:
                continue
            lat, lon = vehicle.get("lat"), vehicle.get("lon")
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            if lat == 0 and lon == 0:
                continue  # agencies send 0,0 when a bus has no GPS fix
            vehicle["id"] = vehicle["id"] or entity_id
            vehicles.append(vehicle)
    if not saw_header and not vehicles:
        raise FeedError("This does not look like a GTFS-Realtime feed.")
    return feed_time, vehicles
