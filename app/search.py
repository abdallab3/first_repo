"""One search from start to finish: crawl the site, rank what was found, report progress."""

import time
from urllib.parse import urlsplit

from .crawler import Crawler
from .ranking import parse_query, rank
from .security import UnsafeURL

EARLY_STOP_MIN_PAGES = 10  # never stop on a first guess
EARLY_STOP_MARGIN = 1.3  # the best page must clearly beat the runner-up

STOP_MESSAGES = {
    "page_limit": "I stopped after reading the most pages one search is allowed to read.",
    "time_limit": "I stopped because the search reached its time limit.",
}


def _is_home(url):
    parts = urlsplit(url)
    return parts.path in ("", "/") and not parts.query


def _rank_without_home(query, docs, top):
    others = [d for d in docs if not _is_home(d.url)]
    return rank(query, others or docs, top=top)


def run_search(start_url, request, session, settings, resolver=None, clock=time.monotonic, sleep=time.sleep):
    """Yield progress events, then one final 'results' (or 'error') event."""
    query = parse_query(request)
    crawler = Crawler(session, query, settings, resolver=resolver, clock=clock, sleep=sleep)
    try:
        for event in crawler.crawl(start_url):
            yield event
            if (
                event["type"] == "progress"
                and crawler.fetched >= EARLY_STOP_MIN_PAGES
                and crawler.fetched % 3 == 0
            ):
                top = _rank_without_home(query, crawler.documents(), 2)
                if (
                    top
                    and top[0]["strength"] == "strong"
                    and (len(top) == 1 or top[0]["score"] >= EARLY_STOP_MARGIN * top[1]["score"])
                ):
                    crawler.stop_reason = "found"
                    break
    except UnsafeURL as e:
        yield {"type": "error", "message": str(e)}
        return

    if crawler.stop_reason in ("robots_unreachable", "robots_blocked", "start_redirect", "start_failed"):
        yield {"type": "error", "message": " ".join(crawler.notes)}
        return

    ranked = _rank_without_home(query, crawler.documents(), 4)
    notes = list(crawler.notes)
    if crawler.stop_reason in STOP_MESSAGES and (not ranked or ranked[0]["strength"] != "strong"):
        notes.append(STOP_MESSAGES[crawler.stop_reason])
    if crawler.failed:
        notes.append(f"{crawler.failed} page(s) could not be read and were skipped.")

    if not ranked:
        yield {
            "type": "results",
            "best": None,
            "others": [],
            "message": "I did not find a page that matches that request.",
            "pages_checked": crawler.fetched,
            "stopped": crawler.stop_reason,
            "notes": notes,
        }
        return

    best = ranked[0]
    message = {
        "strong": "Best match",
        "possible": "Closest match. It may not cover everything you asked for.",
        "weak": "I did not find a clear match. This is the closest page.",
    }[best["strength"]]
    yield {
        "type": "results",
        "best": best,
        "others": ranked[1:],
        "message": message,
        "pages_checked": crawler.fetched,
        "stopped": crawler.stop_reason,
        "notes": notes,
    }
