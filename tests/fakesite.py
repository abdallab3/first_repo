"""A pretend school website, so tests never touch the real internet."""

import io

import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

HOST = "school.example"

PAGES = {
    "/robots.txt": (
        200,
        "text/plain",
        "User-agent: *\nDisallow: /private/\nDisallow: /*?print=\nSitemap: https://school.example/sitemap.xml\n",
    ),
    "/sitemap.xml": (
        200,
        "application/xml",
        """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://school.example/about</loc></url>
  <url><loc>https://school.example/calendar/2024-2025</loc></url>
  <url><loc>https://school.example/calendar/2026-2027</loc></url>
  <url><loc>https://school.example/private/staff-calendar-2026</loc></url>
</urlset>""",
    ),
    "/": (
        200,
        "text/html",
        """<html><head><title>Maple Grove School District</title></head><body>
<header><nav><a href="/about">About</a> <a href="/calendar">Calendars</a> <a href="/contact">Contact</a></nav></header>
<h1>Welcome to Maple Grove</h1>
<p>Serving families since 1952.</p>
<a href="/parents">Parent Information</a>
<a href="/calendar">Calendars</a>
<a href="/lunch">Lunch Menu</a>
<a href="/news/open-house">Open house news</a>
<a href="/broken">Old announcements</a>
<a href="/go-offsite">Partner site</a>
<a href="/go-private">Status page</a>
<a href="/private/staff-calendar-2026">Staff calendar</a>
<a href="mailto:office@school.example">Email us</a>
<a href="https://other.example/calendar">Other site calendar</a>
</body></html>""",
    ),
    "/about": (
        200,
        "text/html",
        "<html><head><title>About Maple Grove</title></head><body><h1>About us</h1><p>Our mission and history.</p>"
        '<a href="/contact">Contact us</a></body></html>',
    ),
    "/contact": (
        200,
        "text/html",
        "<html><head><title>Contact the office</title></head><body><h1>Contact</h1>"
        "<p>Phone 555-0100. Email office@school.example.</p></body></html>",
    ),
    "/parents": (
        200,
        "text/html",
        """<html><head><title>Parent Resources</title></head><body>
<h1>Parent Resources</h1><h2>Concerns and safety</h2>
<p>Use these links to raise a concern, report bullying, or read the handbook.</p>
<a href="/parents/report-a-concern">Report a concern</a>
<a href="/files/parent_handbook.pdf">Parent Handbook (PDF)</a>
<a href="/calendar">School calendars</a></body></html>""",
    ),
    "/parents/report-a-concern": (
        200,
        "text/html",
        "<html><head><title>Report a concern</title></head><body><h1>Report a concern</h1>"
        "<p>Tell us about a safety or bullying concern.</p></body></html>",
    ),
    "/calendar": (
        200,
        "text/html",
        """<html><head><title>Calendars</title></head><body><h1>School Calendars</h1>
<ul>
<li><a href="/calendar/2024-2025">2024-2025 School Calendar</a></li>
<li><a href="/calendar/2026-2027">2026-2027 School Calendar</a></li>
<li><a href="/files/2026-27_district_calendar.pdf">District calendar 2026-27 (PDF)</a></li>
</ul></body></html>""",
    ),
    "/calendar/2024-2025": (
        200,
        "text/html",
        "<html><head><title>2024-2025 School Calendar</title></head><body><h1>2024-2025 School Calendar</h1>"
        "<p>First day of school: August 26, 2024.</p></body></html>",
    ),
    "/calendar/2026-2027": (
        200,
        "text/html",
        "<html><head><title>2026-2027 School Calendar</title></head><body><h1>2026-2027 School Calendar</h1>"
        "<h2>Important dates</h2><p>First day of school: August 24, 2026.</p></body></html>",
    ),
    "/lunch": (
        200,
        "text/html",
        "<html><head><title>Lunch Menu</title></head><body><h1>Lunch Menu</h1><p>Monday: pasta.</p></body></html>",
    ),
    "/news/open-house": (
        200,
        "text/html",
        "<html><head><title>Open house news</title></head><body><h1>Open house</h1>"
        "<p>Join us in the fall.</p></body></html>",
    ),
    "/broken": (500, "text/html", "<html><body>Server error</body></html>"),
    "/private/staff-calendar-2026": (
        200,
        "text/html",
        "<html><head><title>Staff calendar 2026</title></head><body>Staff only 2026 calendar</body></html>",
    ),
    "/files/parent_handbook.pdf": (200, "application/pdf", "%PDF-1.4 fake"),
    "/files/2026-27_district_calendar.pdf": (200, "application/pdf", "%PDF-1.4 fake"),
}

REDIRECTS = {
    "/go-offsite": "https://evil.example/landing",
    "/go-private": "http://169.254.169.254/latest/meta-data/",
}


class FakeAdapter(BaseAdapter):
    """Answers requests from the PAGES table and remembers every address it was asked for."""

    def __init__(self, pages=None, redirects=None, host=HOST):
        super().__init__()
        self.pages = PAGES if pages is None else pages
        self.redirects = REDIRECTS if redirects is None else redirects
        self.host = host
        self.requested = []
        self.user_agents = []

    def send(self, request, **kwargs):
        self.requested.append(request.url)
        self.user_agents.append(request.headers.get("User-Agent", ""))
        from urllib.parse import urlsplit

        parts = urlsplit(request.url)
        path = parts.path or "/"
        resp = requests.Response()
        resp.url = request.url
        resp.request = request
        resp.raw = io.BytesIO(b"")
        resp.headers = CaseInsensitiveDict()
        if parts.hostname != self.host:
            resp.status_code = 404
            resp._content = b""
        elif path in self.redirects:
            resp.status_code = 302
            resp.headers["Location"] = self.redirects[path]
            resp._content = b""
        elif path in self.pages:
            status, ctype, body = self.pages[path]
            resp.status_code = status
            resp.headers["Content-Type"] = ctype
            resp._content = body.encode("utf-8")
        else:
            resp.status_code = 404
            resp.headers["Content-Type"] = "text/html"
            resp._content = b"Not found"
        resp._content_consumed = True
        return resp

    def close(self):
        pass


def fake_session(adapter=None):
    adapter = adapter or FakeAdapter()
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.adapter = adapter
    return session


def public_resolver(host):
    """Pretend every host name points to a public address, except a few named private ones."""
    import ipaddress

    try:
        ipaddress.ip_address(host)
        return [host]  # an address typed in directly is what it says it is
    except ValueError:
        pass
    private = {"private.example": "10.0.0.5", "metadata.example": "169.254.169.254"}
    return [private.get(host, "93.184.216.34")]
