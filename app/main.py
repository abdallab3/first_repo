"""The web app: one page, a health check, and a search endpoint that streams progress."""

import json
import os

import requests
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from . import security
from .config import Settings
from .limiter import ConcurrencyGate, RateLimiter
from .ranking import parse_query
from .search import run_search

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def default_session():
    return requests.Session()


def client_ip(req, hops):
    """The visitor's address. Behind Railway's proxy it is the last entry the proxy added."""
    forwarded = [p.strip() for p in req.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
    if hops > 0 and len(forwarded) >= hops:
        return forwarded[-hops]
    return req.remote_addr or "unknown"


def create_app(settings=None, session_factory=None, resolver=None):
    settings = settings or Settings.from_env()
    session_factory = session_factory or default_session
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024  # a search request is tiny
    limiter = RateLimiter(settings.rate_limit_searches, settings.rate_limit_window)
    gate = ConcurrencyGate(settings.max_concurrent)

    @app.after_request
    def add_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/api/search")
    def search():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="Send the website address and what you want to find."), 400
        site, wanted = body.get("url"), body.get("request")
        if not isinstance(site, str) or not isinstance(wanted, str):
            return jsonify(error="Send the website address and what you want to find."), 400
        try:
            start = security.check_url(site, resolver)
            parse_query(wanted)
        except security.UnsafeURL as e:
            return jsonify(error=str(e)), 400
        except ValueError as e:
            return jsonify(error=str(e)), 400

        allowed, wait = limiter.allow(client_ip(request, settings.trusted_proxy_hops))
        if not allowed:
            resp = jsonify(error="You have searched a lot in a short time. Please wait a little and try again.")
            resp.status_code = 429
            resp.headers["Retry-After"] = str(wait)
            return resp
        if not gate.try_enter():
            resp = jsonify(error="The site is busy right now. Please try again in a minute.")
            resp.status_code = 503
            resp.headers["Retry-After"] = "30"
            return resp

        released = []

        def release():
            if not released:
                released.append(True)
                gate.leave()

        def stream():
            session = session_factory()
            try:
                for event in run_search(start, wanted, session, settings, resolver=resolver):
                    yield json.dumps(event) + "\n"
            except Exception:  # never show a stack trace to a visitor
                app.logger.exception("search failed")
                yield json.dumps({"type": "error", "message": "Something went wrong during the search."}) + "\n"
            finally:
                session.close()
                release()

        response = Response(
            stream_with_context(stream()),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
        response.call_on_close(release)  # frees the slot even if the visitor leaves early
        return response

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), debug=False)
