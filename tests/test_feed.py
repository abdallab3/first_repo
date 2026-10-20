import unittest

import requests

from app.config import Settings
from app.feed import AgencyFeed, DemoFeed
from tests import pbhelp as pb


class FakeResponse:
    def __init__(self, status=200, content=b""):
        self.status_code = status
        self.content = content
        self.closed = False

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i : i + size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None, stream=False):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    def __init__(self, now=1_700_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def settings(**kw):
    return Settings(feed_url="https://agency.example/vehicles.pb", **kw)


def sample(timestamp=1_700_000_000, route="12"):
    return pb.feed(
        [pb.vehicle_entity("e1", route=route, lat=40.75, lon=-73.98, bearing=45.0, speed=5.0,
                           vehicle_id="v1", label="101", timestamp=timestamp)],
        timestamp=timestamp,
    )


class AgencyFeedTests(unittest.TestCase):
    def test_returns_buses_in_the_apps_own_format(self):
        clock = Clock()
        feed = AgencyFeed(settings(), FakeSession(FakeResponse(200, sample(timestamp=1_699_999_990))), clock)
        buses, status = feed.read()
        self.assertTrue(status["ok"])
        self.assertEqual(len(buses), 1)
        bus = buses[0]
        self.assertEqual((bus["route"], bus["label"], bus["source"], bus["riders"]), ("12", "101", "agency", 0))
        self.assertEqual(bus["age"], 10)
        self.assertEqual(bus["bearing"], 45)
        self.assertAlmostEqual(bus["lat"], 40.75, places=4)

    def test_the_agency_is_not_asked_more_often_than_the_setting_allows(self):
        clock = Clock()
        session = FakeSession(FakeResponse(200, sample()))
        feed = AgencyFeed(settings(feed_refresh_seconds=10), session, clock)
        for _ in range(5):
            feed.read()
        self.assertEqual(len(session.calls), 1)
        clock.now += 11
        feed.read()
        self.assertEqual(len(session.calls), 2)

    def test_extra_headers_such_as_an_api_key_are_sent(self):
        session = FakeSession(FakeResponse(200, sample()))
        AgencyFeed(settings(feed_headers=(("x-api-key", "secret"),)), session, Clock()).read()
        self.assertEqual(session.calls[0]["headers"]["x-api-key"], "secret")
        self.assertEqual(session.calls[0]["url"], "https://agency.example/vehicles.pb")

    def test_old_positions_are_hidden(self):
        clock = Clock()
        feed = AgencyFeed(settings(vehicle_max_age=300), FakeSession(FakeResponse(200, sample(timestamp=1_699_999_000))), clock)
        buses, status = feed.read()
        self.assertEqual(buses, [])
        self.assertTrue(status["ok"])

    def test_a_failing_feed_is_reported_and_recent_data_is_kept(self):
        clock = Clock()
        session = FakeSession(FakeResponse(200, sample(timestamp=1_700_000_000)), FakeResponse(503, b"down"))
        feed = AgencyFeed(settings(feed_refresh_seconds=10, vehicle_max_age=300), session, clock)
        self.assertEqual(len(feed.read()[0]), 1)
        clock.now += 20
        buses, status = feed.read()
        self.assertFalse(status["ok"])
        self.assertIn("503", status["error"])
        self.assertEqual(len(buses), 1)  # the last positions are still recent
        clock.now += 400
        buses, status = feed.read()
        self.assertEqual(buses, [])  # but not forever

    def test_network_failures_give_a_plain_message_without_details(self):
        feed = AgencyFeed(settings(), FakeSession(requests.ConnectionError("secret host detail")), Clock())
        buses, status = feed.read()
        self.assertFalse(status["ok"])
        self.assertNotIn("secret", status["error"])
        self.assertEqual(buses, [])

    def test_something_that_is_not_a_feed_is_refused(self):
        feed = AgencyFeed(settings(), FakeSession(FakeResponse(200, b"<html>Sign in</html>")), Clock())
        _, status = feed.read()
        self.assertFalse(status["ok"])

    def test_an_oversized_feed_is_refused(self):
        feed = AgencyFeed(settings(feed_max_bytes=100), FakeSession(FakeResponse(200, sample() * 50)), Clock())
        _, status = feed.read()
        self.assertFalse(status["ok"])
        self.assertIn("larger", status["error"])

    def test_the_connection_is_always_closed(self):
        response = FakeResponse(200, sample())
        AgencyFeed(settings(), FakeSession(response), Clock()).read()
        self.assertTrue(response.closed)


class DemoFeedTests(unittest.TestCase):
    def test_makes_five_buses_on_two_routes_that_move(self):
        clock = Clock(1000.0)
        s = Settings()
        feed = DemoFeed(s, clock)
        first, status = feed.read()
        self.assertTrue(status["ok"])
        self.assertEqual(sorted({b["route"] for b in first}), ["A", "B"])
        self.assertEqual(len(first), 5)
        clock.now += 30
        second, _ = feed.read()
        self.assertNotEqual([(b["lat"], b["lon"]) for b in first], [(b["lat"], b["lon"]) for b in second])

    def test_buses_stay_near_the_map_center(self):
        s = Settings()
        feed = DemoFeed(s, Clock(0.0))
        for t in range(0, 3000, 97):
            feed.clock.now = float(t)
            for b in feed.read()[0]:
                self.assertLess(abs(b["lat"] - s.center_lat), 0.03)
                self.assertLess(abs(b["lon"] - s.center_lon), 0.05)
                self.assertTrue(0 <= b["bearing"] < 360)


if __name__ == "__main__":
    unittest.main()
