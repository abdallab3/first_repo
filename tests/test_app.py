import json
import unittest

import requests

from app.config import Settings
from app.main import client_ip, create_app
from tests.fakesite import FakeAdapter, fake_session, public_resolver


def make_client(**overrides):
    settings = Settings(request_delay=0, max_seconds=60, **overrides)
    adapter = FakeAdapter()
    app = create_app(settings, session_factory=lambda: fake_session(adapter), resolver=public_resolver)
    return app.test_client(), adapter


def post(client, body, headers=None):
    return client.post("/api/search", json=body, headers=headers or {})


def events(response):
    return [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line.strip()]


class Pages(unittest.TestCase):
    def test_home_page_and_health_check(self):
        client, _ = make_client()
        with client.get("/") as home:
            self.assertEqual(home.status_code, 200)
            self.assertIn("Website Navigator", home.get_data(as_text=True))
        self.assertEqual(client.get("/health").get_json(), {"status": "ok"})
        for path in ["/static/app.js", "/static/style.css"]:
            with client.get(path) as static:
                self.assertEqual(static.status_code, 200, path)

    def test_security_headers(self):
        client, _ = make_client()
        response = client.get("/health")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")


class Searching(unittest.TestCase):
    def test_a_search_streams_progress_and_a_result(self):
        client, _ = make_client()
        response = post(client, {"url": "school.example", "request": "find the 2026 school calendar"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/x-ndjson", response.headers["Content-Type"])
        lines = events(response)
        self.assertEqual(lines[-1]["type"], "results")
        self.assertEqual(lines[-1]["best"]["url"], "https://school.example/calendar/2026-2027")
        self.assertTrue(any(e["type"] == "progress" for e in lines))

    def test_bad_requests_get_clear_errors(self):
        client, adapter = make_client()
        cases = [
            (None, "Send the website"),
            ({}, "Send the website"),
            ({"url": 5, "request": "x"}, "Send the website"),
            ({"url": "school.example", "request": ""}, "Tell me what to find"),
            ({"url": "school.example", "request": "the page"}, "Tell me what to find"),
            ({"url": "", "request": "calendar"}, "Enter the address"),
            ({"url": "http://localhost/", "request": "calendar"}, "private network"),
            ({"url": "http://127.0.0.1:8080/", "request": "calendar"}, "standard web ports"),
            ({"url": "http://169.254.169.254/", "request": "calendar"}, "private network"),
            ({"url": "ftp://school.example/", "request": "calendar"}, "http and https"),
            ({"url": "school.example", "request": "calendar " * 100}, "too long"),
        ]
        for body, expected in cases:
            response = post(client, body) if body is not None else client.post("/api/search", data="not json")
            self.assertEqual(response.status_code, 400, body)
            self.assertIn(expected, response.get_json()["error"], body)
        self.assertEqual(adapter.requested, [])

    def test_huge_requests_are_refused(self):
        client, _ = make_client()
        response = client.post("/api/search", data="x" * 20000, content_type="application/json")
        self.assertEqual(response.status_code, 413)

    def test_visitors_are_rate_limited(self):
        client, _ = make_client(rate_limit_searches=3)
        body = {"url": "school.example", "request": "school calendar"}
        headers = {"X-Forwarded-For": "1.2.3.4"}
        for _ in range(3):
            self.assertEqual(post(client, body, headers).status_code, 200)
        blocked = post(client, body, headers)
        self.assertEqual(blocked.status_code, 429)
        self.assertTrue(int(blocked.headers["Retry-After"]) > 0)
        self.assertEqual(post(client, body, {"X-Forwarded-For": "5.6.7.8"}).status_code, 200)

    def test_a_visitor_cannot_dodge_the_limit_by_faking_the_forwarded_header(self):
        client, _ = make_client(rate_limit_searches=1)
        body = {"url": "school.example", "request": "school calendar"}
        self.assertEqual(post(client, body, {"X-Forwarded-For": "9.9.9.1, 1.2.3.4"}).status_code, 200)
        self.assertEqual(post(client, body, {"X-Forwarded-For": "9.9.9.2, 1.2.3.4"}).status_code, 429)

    def test_the_server_slot_is_freed_after_each_search(self):
        client, _ = make_client(max_concurrent=1, rate_limit_searches=100)
        body = {"url": "school.example", "request": "school calendar"}
        for _ in range(3):
            self.assertEqual(post(client, body).status_code, 200)

    def test_unexpected_failures_do_not_leak_details(self):
        class Boom(requests.Session):
            def get(self, *a, **k):
                raise RuntimeError("secret internal detail")

        app = create_app(Settings(request_delay=0), session_factory=Boom, resolver=public_resolver)
        response = post(app.test_client(), {"url": "school.example", "request": "calendar"})
        body = response.get_data(as_text=True)
        self.assertNotIn("secret internal detail", body)
        self.assertEqual(events(response)[-1]["type"], "error")


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


if __name__ == "__main__":
    unittest.main()
