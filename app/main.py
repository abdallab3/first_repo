"""The Bus Tracker web app: a map page, bus positions from the agency's feed, and rider sharing."""

import os
import time
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_from_directory

from .config import Settings
from .feed import AgencyFeed, DemoFeed
from .geo import distance_m
from .limiter import RateLimiter
from .riders import RiderError, RiderStore

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SAME_BUS_METERS = 120  # a rider this close to an agency bus on the same route is on that bus


def client_ip(req, hops):
    """The visitor's address. Behind Railway's proxy it is the last entry the proxy added."""
    forwarded = [p.strip() for p in req.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
    if hops > 0 and len(forwarded) >= hops:
        return forwarded[-hops]
    return req.remote_addr or "unknown"


def content_security_policy(tile_url):
    tile_host = urlsplit(tile_url.replace("{s}", "a")).netloc
    images = "img-src 'self' data:" + (f" https://{tile_host}" if tile_host else "")
    return (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        f"{images}; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )


def merge_buses(agency_buses, rider_buses):
    """Add rider-reported buses, unless an agency bus on the same route is already there."""
    merged = [dict(b) for b in agency_buses]
    for rb in rider_buses:
        route = rb["route"].strip().lower()
        twin = None
        for ab in merged:
            if ab["source"] != "agency":
                continue
            names = {ab["route"].strip().lower(), ab["label"].strip().lower()} - {""}
            if route in names and distance_m(ab["lat"], ab["lon"], rb["lat"], rb["lon"]) <= SAME_BUS_METERS:
                twin = ab
                break
        if twin:
            twin["riders"] += rb["riders"]
        else:
            merged.append(rb)
    return merged


def create_app(settings=None, feed=None, riders=None, clock=time.time):
    settings = settings or Settings.from_env()
    if feed is None:
        feed = AgencyFeed(settings, clock=clock) if settings.feed_url else DemoFeed(settings, clock=clock)
    riders = riders or RiderStore(settings, clock=clock)
    csp = content_security_policy(settings.tile_url)

    reads = RateLimiter(settings.rate_limit_reads, settings.rate_limit_read_window)
    reports = RateLimiter(settings.rate_limit_reports, settings.rate_limit_report_window)
    starts = RateLimiter(settings.rate_limit_starts, settings.rate_limit_start_window)

    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024  # every request from the page is tiny

    @app.after_request
    def add_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=()"
        return response

    def limited(limiter, message):
        allowed, wait = limiter.allow(client_ip(request, settings.trusted_proxy_hops))
        if allowed:
            return None
        resp = jsonify(error=message)
        resp.status_code = 429
        resp.headers["Retry-After"] = str(wait)
        return resp

    def body_dict():
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else None

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/config")
    def config():
        resp = jsonify(
            mode=feed.mode,
            agency=settings.agency_name,
            center=[settings.center_lat, settings.center_lon],
            zoom=14.0 if feed.mode == "demo" else settings.zoom,
            tileUrl=settings.tile_url,
            attribution=settings.tile_attribution,
            refreshSeconds=int(settings.feed_refresh_seconds),
        )
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/api/buses")
    def buses():
        blocked = limited(reads, "The map is refreshing too often. Please wait a moment.")
        if blocked:
            return blocked
        agency_buses, status = feed.read()
        rider_buses = riders.buses()
        merged = merge_buses(agency_buses, rider_buses)
        notes = []
        if feed.mode == "demo":
            notes.append("Demo mode: these buses are simulated. No transit agency is connected yet.")
        elif not status["ok"]:
            notes.append(status["error"] + " Showing the last positions it sent, if they are recent.")
        resp = jsonify(
            mode=feed.mode,
            agency=settings.agency_name,
            serverTime=round(time.time()),
            updated=None if status["updated"] is None else round(status["updated"]),
            feedOk=status["ok"],
            buses=merged,
            routes=sorted({b["route"] for b in merged if b["route"]}, key=str.lower),
            notes=notes,
        )
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/api/riders/start")
    def rider_start():
        body = body_dict()
        if body is None:
            return jsonify(error="Send the route you are on."), 400
        blocked = limited(starts, "You have started sharing a lot in a short time. Please wait a little.")
        if blocked:
            return blocked
        try:
            sid = riders.start(body.get("route"), client_ip(request, settings.trusted_proxy_hops))
        except RiderError as e:
            return jsonify(error=e.message), e.status
        return jsonify(session=sid, minSeconds=settings.rider_min_interval)

    @app.post("/api/riders/report")
    def rider_report():
        body = body_dict()
        if body is None:
            return jsonify(error="Send your position."), 400
        blocked = limited(reports, "Too many position reports. Please slow down.")
        if blocked:
            return blocked
        try:
            result = riders.report(body.get("session"), body.get("lat"), body.get("lon"), body.get("accuracy"))
        except RiderError as e:
            return jsonify(error=e.message), e.status
        return jsonify(result=result)

    @app.post("/api/riders/stop")
    def rider_stop():
        body = body_dict()
        if body is not None and isinstance(body.get("session"), str):
            riders.stop(body["session"])
        return jsonify(result="stopped")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), debug=False)
