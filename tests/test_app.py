import unittest

from app.config import Settings
from app.main import client_ip, content_security_policy, create_app, merge_buses
from tests.test_feed import Clock


class StubFeed:
    mode = "live"

    def __init__(self, buses, ok=True, error=None):
        self.buses, self.ok, self.error = buses, ok, error

    def read(self):
        return self.buses, {"ok": self.ok, "updated": 1_700_000_000 if self.ok else None, "error": self.error}


def agency_bus(route="12", lat=40.75, lon=-73.98, label="101"):
    return {"id": "a:" + label, "route": route, "label": label, "lat": lat, "lon": lon, "bearing": 90,
            "speed": 5.0, "age": 3, "source": "agency", "riders": 0}


def rider_bus(route="12", lat=40.75, lon=-73.98, riders=1):
    return {"id": "r:abc", "route": route, "label": "", "lat": lat, "lon": lon, "bearing": None,
            "speed": None, "age": 1, "source": "riders", "riders": riders}


def make(feed=None, clock=None, **kw):
    clock = clock or Clock(1_700_000_000.0)
    app = create_app(Settings(**kw), feed=feed, clock=clock)
    return app.test_client(), clock


class Pages(unittest.TestCase):
    def test_the_page_its_files_and_the_health_check(self):
        client, _ = make()
        with client.get("/") as home:
            self.assertEqual(home.status_code, 200)
            self.assertIn("Bus Tracker", home.get_data(as_text=True))
        self.assertEqual(client.get("/health").get_json(), {"status": "ok"})
        for path in ["/static/app.js", "/static/map.js", "/static/style.css"]:
            with client.get(path) as static:
                self.assertEqual(static.status_code, 200, path)

    def test_the_old_website_navigator_is_gone(self):
        client, _ = make()
        self.assertEqual(client.post("/api/search", json={"url": "x.com", "request": "y"}).status_code, 404)

    def test_security_headers(self):
        client, _ = make()
        r = client.get("/health")
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertIn("https://tile.openstreetmap.org", csp)
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("geolocation=(self)", r.headers["Permissions-Policy"])

    def test_the_map_tile_host_comes_from_the_setting(self):
        csp = content_security_policy("https://{s}.tiles.example.org/{z}/{x}/{y}.png")
        self.assertIn("https://a.tiles.example.org", csp)


class Buses(unittest.TestCase):
    def test_demo_mode_is_clearly_labeled(self):
        client, _ = make()
        cfg = client.get("/api/config").get_json()
        self.assertEqual(cfg["mode"], "demo")
        data = client.get("/api/buses").get_json()
        self.assertEqual(data["mode"], "demo")
        self.assertEqual(len(data["buses"]), 5)
        self.assertEqual(data["routes"], ["A", "B"])
        self.assertTrue(any("simulated" in n for n in data["notes"]))

    def test_live_mode_shows_the_agencys_buses(self):
        client, _ = make(feed=StubFeed([agency_bus("12"), agency_bus("7", label="7")]), agency_name="Metro Transit")
        data = client.get("/api/buses").get_json()
        self.assertEqual(data["mode"], "live")
        self.assertEqual(data["agency"], "Metro Transit")
        self.assertEqual(data["routes"], ["12", "7"])
        self.assertTrue(data["feedOk"])
        self.assertEqual(data["notes"], [])

    def test_a_feed_problem_is_explained_to_the_visitor(self):
        client, _ = make(feed=StubFeed([], ok=False, error="The agency's feed could not be reached."))
        data = client.get("/api/buses").get_json()
        self.assertFalse(data["feedOk"])
        self.assertIn("could not be reached", data["notes"][0])

    def test_visitors_cannot_refresh_endlessly(self):
        client, _ = make(rate_limit_reads=3)
        codes = [client.get("/api/buses").status_code for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])
        self.assertTrue(int(client.get("/api/buses").headers["Retry-After"]) > 0)


class Merging(unittest.TestCase):
    def test_a_rider_on_an_agency_bus_confirms_it_instead_of_adding_a_second_dot(self):
        merged = merge_buses([agency_bus("12")], [rider_bus("12", lat=40.7505, riders=2)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["riders"], 2)

    def test_riders_on_a_route_the_agency_does_not_cover_get_their_own_dot(self):
        merged = merge_buses([agency_bus("12")], [rider_bus("99")])
        self.assertEqual([b["source"] for b in merged], ["agency", "riders"])

    def test_a_rider_far_from_the_agency_bus_gets_their_own_dot(self):
        merged = merge_buses([agency_bus("12")], [rider_bus("12", lat=40.80)])
        self.assertEqual(len(merged), 2)

    def test_the_original_list_is_not_changed(self):
        original = [agency_bus("12")]
        merge_buses(original, [rider_bus("12")])
        self.assertEqual(original[0]["riders"], 0)


class RiderFlow(unittest.TestCase):
    def start(self, client, route="A", headers=None):
        r = client.post("/api/riders/start", json={"route": route}, headers=headers or {})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()["session"]

    def test_a_rider_appears_on_the_map_and_disappears_when_they_stop(self):
        client, clock = make(feed=StubFeed([]))
        sid = self.start(client, "99")
        for i in range(3):
            r = client.post("/api/riders/report", json={"session": sid, "lat": 40.75 + i * 0.001, "lon": -73.98, "accuracy": 8})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.get_json(), {"result": "ok"})
            clock.now += 4
        buses = client.get("/api/buses").get_json()["buses"]
        self.assertEqual(len(buses), 1)
        self.assertEqual((buses[0]["source"], buses[0]["route"], buses[0]["riders"]), ("riders", "99", 1))
        self.assertNotIn(sid, str(buses))
        self.assertEqual(client.post("/api/riders/stop", json={"session": sid}).get_json(), {"result": "stopped"})
        self.assertEqual(client.get("/api/buses").get_json()["buses"], [])

    def test_bad_requests_get_clear_errors(self):
        client, _ = make()
        self.assertEqual(client.post("/api/riders/start", data="nope").status_code, 400)
        self.assertEqual(client.post("/api/riders/start", json=[1]).status_code, 400)
        bad_route = client.post("/api/riders/start", json={"route": "<b>"})
        self.assertEqual(bad_route.status_code, 400)
        self.assertIn("Route names", bad_route.get_json()["error"])
        self.assertEqual(client.post("/api/riders/report", data="nope").status_code, 400)
        gone = client.post("/api/riders/report", json={"session": "x", "lat": 40, "lon": -70, "accuracy": 5})
        self.assertEqual(gone.status_code, 404)
        self.assertEqual(client.post("/api/riders/stop", data="nope").status_code, 200)  # stopping is always safe

    def test_position_reports_are_rate_limited(self):
        client, _ = make(rate_limit_reports=2)
        sid = self.start(client)
        codes = [
            client.post("/api/riders/report", json={"session": sid, "lat": 40.75, "lon": -73.98, "accuracy": 5}).status_code
            for _ in range(4)
        ]
        self.assertEqual(codes[2:], [429, 429])

    def test_starting_is_rate_limited(self):
        client, _ = make(rate_limit_starts=2, max_riders_per_visitor=50)
        codes = [client.post("/api/riders/start", json={"route": "1"}).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_huge_requests_are_refused(self):
        client, _ = make()
        r = client.post("/api/riders/start", data="x" * 10000, content_type="application/json")
        self.assertEqual(r.status_code, 413)


class ClientAddress(unittest.TestCase):
    class Req:
        def __init__(self, forwarded, remote="10.1.1.1"):
            self.headers = {"X-Forwarded-For": forwarded} if forwarded else {}
            self.remote_addr = remote

    def test_the_address_the_proxy_added_is_used(self):
        self.assertEqual(client_ip(self.Req("evil, 1.2.3.4"), 1), "1.2.3.4")
        self.assertEqual(client_ip(self.Req("evil, 1.2.3.4, 10.0.0.9"), 2), "1.2.3.4")

    def test_without_the_header_the_direct_address_is_used(self):
        self.assertEqual(client_ip(self.Req(""), 1), "10.1.1.1")
        self.assertEqual(client_ip(self.Req("1.2.3.4"), 0), "10.1.1.1")

    def test_a_visitor_cannot_dodge_the_limit_by_faking_the_forwarded_header(self):
        client, _ = make(rate_limit_reads=1)
        first = client.get("/api/buses", headers={"X-Forwarded-For": "9.9.9.1, 1.2.3.4"})
        second = client.get("/api/buses", headers={"X-Forwarded-For": "9.9.9.2, 1.2.3.4"})
        self.assertEqual((first.status_code, second.status_code), (200, 429))


class Settings_(unittest.TestCase):
    def test_environment_values_are_read_safely(self):
        import os
        from unittest import mock

        env = {
            "FEED_URL": " https://agency.example/rt ",
            "FEED_HEADERS": '{"x-api-key": "k"}',
            "MAP_CENTER": "41.5,-87.6",
            "MAP_ZOOM": "99",
            "FEED_REFRESH_SECONDS": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            s = Settings.from_env()
        self.assertEqual(s.feed_url, "https://agency.example/rt")
        self.assertEqual(s.feed_headers, (("x-api-key", "k"),))
        self.assertEqual((s.center_lat, s.center_lon), (41.5, -87.6))
        self.assertEqual(s.zoom, 18.0)  # kept in range
        self.assertEqual(s.feed_refresh_seconds, 5.0)  # never hammers the agency

    def test_broken_environment_values_fall_back_to_defaults(self):
        import os
        from unittest import mock

        env = {"FEED_HEADERS": "not json", "MAP_CENTER": "abc", "MAP_ZOOM": "far", "TRUSTED_PROXY_HOPS": "x"}
        with mock.patch.dict(os.environ, env, clear=False):
            s = Settings.from_env()
        d = Settings()
        self.assertEqual((s.feed_headers, s.center_lat, s.zoom, s.trusted_proxy_hops), ((), d.center_lat, d.zoom, 1))


if __name__ == "__main__":
    unittest.main()
