"""Settings for the Website Navigator. Every value can be changed with an environment variable."""

import os
from dataclasses import dataclass


def _number(name, default, cast):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # How much of a site one search may read.
    max_pages: int = 40  # pages fetched per search
    max_seconds: float = 25.0  # total time per search
    request_delay: float = 0.4  # pause between requests to the same site, in seconds
    max_crawl_delay: float = 5.0  # longest robots.txt Crawl-delay we will honor
    request_timeout: float = 8.0  # per request
    max_bytes: int = 1_000_000  # bytes read from one page
    max_redirects: int = 5
    max_candidates: int = 3000  # links remembered per search
    max_sitemap_files: int = 3
    # Who may use it, and how much.
    rate_limit_searches: int = 10  # searches allowed per visitor...
    rate_limit_window: int = 600  # ...in this many seconds
    max_concurrent: int = 4  # searches running at once on the server
    trusted_proxy_hops: int = 1  # proxies in front of the app (Railway adds one)
    # How the crawler introduces itself.
    user_agent: str = (
        "WebsiteNavigatorBot/1.0 (+https://github.com/abdallab3/first_repo)"
    )
    robots_token: str = "websitenavigatorbot"

    @classmethod
    def from_env(cls):
        d = cls()
        return cls(
            max_pages=_number("MAX_PAGES", d.max_pages, int),
            max_seconds=_number("MAX_SECONDS", d.max_seconds, float),
            request_delay=_number("REQUEST_DELAY", d.request_delay, float),
            rate_limit_searches=_number("RATE_LIMIT_SEARCHES", d.rate_limit_searches, int),
            rate_limit_window=_number("RATE_LIMIT_WINDOW", d.rate_limit_window, int),
            max_concurrent=_number("MAX_CONCURRENT", d.max_concurrent, int),
            trusted_proxy_hops=_number("TRUSTED_PROXY_HOPS", d.trusted_proxy_hops, int),
        )
