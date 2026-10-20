"""Builds GTFS-Realtime messages for tests, so tests never depend on a real agency."""

import struct


def varint(n):
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def key(number, wire):
    return varint((number << 3) | wire)


def string(number, text):
    data = text.encode()
    return key(number, 2) + varint(len(data)) + data


def message(number, body):
    return key(number, 2) + varint(len(body)) + body


def uint(number, value):
    return key(number, 0) + varint(value)


def flt(number, value):
    return key(number, 5) + struct.pack("<f", value)


def vehicle_entity(entity_id, route="", lat=None, lon=None, bearing=None, speed=None,
                   vehicle_id=None, label=None, timestamp=None, trip="", deleted=False, extra=b""):
    position = b""
    if lat is not None:
        position += flt(1, lat)
    if lon is not None:
        position += flt(2, lon)
    if bearing is not None:
        position += flt(3, bearing)
    if speed is not None:
        position += flt(5, speed)
    body = b""
    if route or trip:
        body += message(1, (string(1, trip) if trip else b"") + (string(5, route) if route else b""))
    if position:
        body += message(2, position)
    if timestamp is not None:
        body += uint(5, timestamp)
    if vehicle_id is not None or label is not None:
        body += message(8, (string(1, vehicle_id) if vehicle_id is not None else b"")
                        + (string(2, label) if label is not None else b""))
    body += extra
    entity = string(1, entity_id)
    if deleted:
        entity += uint(2, 1)
    entity += message(4, body)
    return message(2, entity)


def feed(entities, timestamp=None):
    header = string(1, "2.0") + uint(2, 0) + (uint(3, timestamp) if timestamp is not None else b"")
    return message(1, header) + b"".join(entities)
