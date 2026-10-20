import unittest

from app.config import Settings
from app.riders import RiderError, RiderStore

LAT, LON = 40.7500, -73.9800
STEP = 0.001  # about 111 meters of latitude


class Clock:
    def __init__(self):
        self.now = 10_000.0

    def __call__(self):
        return self.now


def store(**kw):
    clock = Clock()
    return RiderStore(Settings(**kw), clock=clock), clock


def ride(rs, clock, route="12", ip="1.1.1.1", moves=2, lat=LAT, lon=LON):
    """Start a rider and move them far enough to count as on a moving bus."""
    sid = rs.start(route, ip)
    rs.report(sid, lat, lon, 10)
    for i in range(1, moves + 1):
        clock.now += 4
        rs.report(sid, lat + i * STEP, lon, 10)
    return sid


class Starting(unittest.TestCase):
    def test_route_names_are_checked(self):
        rs, _ = store()
        for bad in [None, 5, "", "   ", "x" * 41, "<script>", "12; drop", "a\nb\x00"]:
            with self.assertRaises(RiderError, msg=repr(bad)):
                rs.start(bad, "ip")
        for good in ["12", "M15-SBS", "Route 7 / Express", "Línea 3", "B&C #2"]:
            self.assertTrue(rs.start(good, "ip"))

    def test_one_visitor_cannot_start_unlimited_sessions(self):
        rs, _ = store(max_riders_per_visitor=2)
        rs.start("1", "a")
        rs.start("1", "a")
        with self.assertRaises(RiderError) as caught:
            rs.start("1", "a")
        self.assertEqual(caught.exception.status, 429)
        rs.start("1", "b")  # someone else can

    def test_the_server_has_a_cap_on_riders(self):
        rs, _ = store(max_riders=2, max_riders_per_visitor=9)
        rs.start("1", "a")
        rs.start("1", "b")
        with self.assertRaises(RiderError) as caught:
            rs.start("1", "c")
        self.assertEqual(caught.exception.status, 503)


class Reporting(unittest.TestCase):
    def test_bad_positions_are_refused(self):
        rs, _ = store()
        sid = rs.start("12", "ip")
        for lat, lon, acc in [(91, 0, 5), (0, 200, 5), ("40", "-70", 5), (None, None, 5), (LAT, LON, -1), (LAT, LON, True)]:
            with self.assertRaises(RiderError, msg=(lat, lon, acc)):
                rs.report(sid, lat, lon, acc)

    def test_an_unknown_or_ended_session_gets_a_404(self):
        rs, _ = store()
        for sid in ["nope", None, 5]:
            with self.assertRaises(RiderError) as caught:
                rs.report(sid, LAT, LON, 5)
            self.assertEqual(caught.exception.status, 404)

    def test_reports_cannot_come_faster_than_the_limit(self):
        rs, clock = store(rider_min_interval=3)
        sid = rs.start("12", "ip")
        rs.report(sid, LAT, LON, 5)
        clock.now += 1
        with self.assertRaises(RiderError) as caught:
            rs.report(sid, LAT, LON, 5)
        self.assertEqual(caught.exception.status, 429)
        clock.now += 3
        self.assertEqual(rs.report(sid, LAT, LON, 5), "ok")

    def test_a_vague_position_is_ignored_but_keeps_the_session_alive(self):
        rs, clock = store(rider_max_accuracy=100)
        sid = rs.start("12", "ip")
        self.assertEqual(rs.report(sid, LAT, LON, 500), "ignored")
        clock.now += 4
        self.assertEqual(rs.report(sid, LAT, LON, None), "ok")  # no accuracy given is accepted
        self.assertEqual(rs.active_count(), 1)

    def test_a_jump_no_bus_could_make_is_refused(self):
        rs, clock = store(rider_max_speed=35)
        sid = rs.start("12", "ip")
        rs.report(sid, LAT, LON, 5)
        clock.now += 4
        with self.assertRaises(RiderError):
            rs.report(sid, LAT + 0.05, LON, 5)  # about 5.5 km in 4 seconds
        clock.now += 4
        self.assertEqual(rs.report(sid, LAT + STEP, LON, 5), "ok")  # the old position was kept


class WhatOthersSee(unittest.TestCase):
    def test_a_rider_who_is_not_moving_is_not_shown(self):
        rs, clock = store()
        sid = rs.start("12", "ip")
        for _ in range(4):
            rs.report(sid, LAT, LON, 5)
            clock.now += 4
        self.assertEqual(rs.buses(), [])

    def test_a_moving_rider_becomes_a_bus(self):
        rs, clock = store()
        ride(rs, clock)
        buses = rs.buses()
        self.assertEqual(len(buses), 1)
        bus = buses[0]
        self.assertEqual((bus["route"], bus["source"], bus["riders"]), ("12", "riders", 1))
        self.assertAlmostEqual(bus["lat"], LAT + 2 * STEP, places=5)
        self.assertEqual(bus["bearing"], 0)  # heading north
        self.assertGreater(bus["speed"], 20)
        self.assertEqual(bus["age"], 0)

    def test_the_bus_goes_away_when_the_rider_stops_moving_or_goes_quiet(self):
        rs, clock = store(rider_move_window=180, rider_ttl=120)
        sid = ride(rs, clock)
        self.assertEqual(len(rs.buses()), 1)
        # Still reporting, but standing still for longer than the window.
        for _ in range(50):
            clock.now += 4
            rs.report(sid, LAT + 2 * STEP, LON, 5)
        self.assertEqual(rs.buses(), [])
        # Moving again brings it back.
        clock.now += 4
        rs.report(sid, LAT + 3 * STEP, LON, 5)
        self.assertEqual(len(rs.buses()), 1)
        # Silence ends the session.
        clock.now += 121
        self.assertEqual(rs.buses(), [])
        self.assertEqual(rs.active_count(), 0)

    def test_riders_on_the_same_bus_become_one_dot(self):
        rs, clock = store()
        ride(rs, clock, ip="a")
        ride(rs, clock, ip="b", lon=LON + 0.0003)  # about 25 m away
        buses = rs.buses()
        self.assertEqual(len(buses), 1)
        self.assertEqual(buses[0]["riders"], 2)

    def test_route_names_are_matched_without_regard_to_capitals(self):
        rs, clock = store()
        ride(rs, clock, route="m15", ip="a")
        ride(rs, clock, route="M15", ip="b")
        self.assertEqual(len(rs.buses()), 1)

    def test_other_routes_and_far_away_riders_stay_separate(self):
        rs, clock = store()
        ride(rs, clock, route="12", ip="a")
        ride(rs, clock, route="14", ip="b")
        ride(rs, clock, route="12", ip="c", lat=LAT + 0.02)
        self.assertEqual(len(rs.buses()), 3)

    def test_nothing_that_identifies_a_rider_is_shown(self):
        rs, clock = store()
        sid = ride(rs, clock, ip="203.0.113.9")
        text = repr(rs.buses())
        self.assertNotIn(sid, text)
        self.assertNotIn("203.0.113.9", text)

    def test_stopping_removes_the_rider_at_once(self):
        rs, clock = store()
        sid = ride(rs, clock)
        rs.stop(sid)
        rs.stop("unknown")  # harmless
        self.assertEqual(rs.buses(), [])
        self.assertEqual(rs.active_count(), 0)


if __name__ == "__main__":
    unittest.main()
