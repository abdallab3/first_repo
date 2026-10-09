"""A polite crawler that stays on one website and looks for pages that match a request."""

import heapq
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from . import security
from .ranking import Doc, kind_of_url, quick_score
from .security import UnsafeURL, site_key

REDIRECTS = {301, 302, 303, 307, 308}
SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".bmp", ".mp3", ".mp4", ".mov",
    ".avi", ".wav", ".zip", ".gz", ".tar", ".rar", ".7z", ".css", ".js", ".woff", ".woff2",
    ".ttf", ".eot", ".exe", ".dmg", ".apk", ".xml", ".json", ".rss",
)
NOT_PAGES = ("#", "mailto:", "tel:", "javascript:", "data:", "sms:")
MAX_PATH_DEPTH = 12
MAX_QUERY_VARIANTS = 5


class FetchError(Exception):
    """A page could not be read. The search carries on without it."""


class OffSiteRedirect(FetchError):
    def __init__(self, url):
        super().__init__("redirected to another website")
        self.url = url


@dataclass
class Fetched:
    status: int
    url: str
    content_type: str
    data: bytes


# ----------------------------------------------------------------------------- robots.txt


class Robots:
    """The rules in a site's robots.txt, with * and $ wildcards, as RFC 9309 describes."""

    def __init__(self, token, allow_all=True, disallow_all=False):
        self.token = token
        self.allow_all = allow_all
        self.disallow_all = disallow_all
        self.rules = []  # (allow, pattern, compiled)
        self.delay = None
        self.sitemaps = []

    @classmethod
    def unreachable(cls, token):
        return cls(token, allow_all=False, disallow_all=True)

    @classmethod
    def parse(cls, text, token):
        groups, current, in_agents = [], None, False
        sitemaps = []
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            name, value = name.strip().lower(), value.strip()
            if name == "user-agent":
                if not in_agents:
                    current = {"agents": [], "rules": [], "delay": None}
                    groups.append(current)
                current["agents"].append(value.lower())
                in_agents = True
                continue
            in_agents = False
            if name == "sitemap":
                sitemaps.append(value)
            elif current is None:
                continue
            elif name in ("allow", "disallow"):
                if value and (value.startswith("/") or value.startswith("*")):
                    current["rules"].append((name == "allow", value))
            elif name == "crawl-delay":
                try:
                    current["delay"] = float(value)
                except ValueError:
                    pass
        specific = [g for g in groups if any(a == token or a == "websitenavigator" for a in g["agents"])]
        chosen = specific or [g for g in groups if "*" in g["agents"]]
        robots = cls(token)
        robots.sitemaps = sitemaps
        for g in chosen:
            for allow, pattern in g["rules"]:
                robots.rules.append((allow, pattern, cls._compile(pattern)))
            if g["delay"] is not None:
                robots.delay = g["delay"]
        return robots

    @staticmethod
    def _compile(pattern):
        anchored = pattern.endswith("$")
        if anchored:
            pattern = pattern[:-1]
        body = re.escape(pattern).replace(r"\*", ".*")
        return re.compile("^" + body + ("$" if anchored else ""))

    def allowed(self, url):
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        if parts.path == "/robots.txt":
            return True
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        best = None
        for allow, pattern, rx in self.rules:
            if rx.match(target):
                key = (len(pattern), allow)
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]


# ----------------------------------------------------------------------------- parsing


def clean_link(base, href):
    """Turn a link found on a page into a plain http(s) address, or None to skip it."""
    href = (href or "").strip()
    if not href or href.lower().startswith(NOT_PAGES):
        return None
    try:
        parts = urlsplit(urljoin(base, href))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    path = parts.path or "/"
    if path.lower().endswith(SKIP_EXTENSIONS) or path.count("/") > MAX_PATH_DEPTH:
        return None
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, parts.query, ""))


def _text(node):
    return " ".join(node.get_text(" ", strip=True).split())


def parse_html(data, base_url):
    """Pull the title, headings, text and links out of a page."""
    soup = BeautifulSoup(data, "lxml")
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = urljoin(base_url, base_tag["href"])
    title = _text(soup.title) if soup.title else ""
    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    description = " ".join((meta.get("content") or "").split()) if meta else ""
    headings = [t for t in (_text(h) for h in soup.find_all(["h1", "h2", "h3"])) if t][:20]
    links = []
    for a in soup.find_all("a", href=True):
        text = _text(a)
        if not text:
            text = a.get("title") or a.get("aria-label") or ""
            if not text:
                img = a.find("img", alt=True)
                text = img["alt"] if img else ""
        url = clean_link(base_url, a["href"])
        if url:
            links.append((url, " ".join(text.split())))
    scripts = len(soup.find_all("script"))
    # Menus and footers repeat on every page, so leave them out of the page text.
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"]):
        tag.decompose()
    body = " ".join(soup.get_text(" ", strip=True).split())[:50000]
    return {
        "title": title[:300],
        "description": description[:500],
        "headings": headings,
        "body": body,
        "links": links,
        "scripts": scripts,
    }


def parse_sitemap(data):
    """Return (page addresses, other sitemap files) listed in a sitemap."""
    soup = BeautifulSoup(data, "xml")
    sitemaps = [loc.get_text(strip=True) for sm in soup.find_all("sitemap") for loc in sm.find_all("loc")]
    urls = [u.find("loc").get_text(strip=True) for u in soup.find_all("url") if u.find("loc")]
    return urls, sitemaps


# ----------------------------------------------------------------------------- crawler


class Crawler:
    def __init__(self, session, query, settings, resolver=None, clock=time.monotonic, sleep=time.sleep):
        self.session = session
        self.query = query
        self.s = settings
        self.resolver = resolver
        self.clock = clock
        self.sleep = sleep
        self.headers = {
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.8,*/*;q=0.5",
        }
        self.docs = {}
        self.visited = set()
        self.frontier = []
        self.counter = 0
        self.robots = None
        self.site = None
        self.origin = None
        self.delay = settings.request_delay
        self.fetched = 0
        self.failed = 0
        self.notes = []
        self.stop_reason = None
        self.started = None
        self._last_request = None
        self._query_variants = {}

    # -- fetching ----------------------------------------------------------------

    def _remaining(self):
        return self.s.max_seconds - (self.clock() - self.started)

    def _pause(self):
        if self._last_request is not None:
            wait = self.delay - (self.clock() - self._last_request)
            if wait > 0:
                self.sleep(wait)
        self._last_request = self.clock()

    def _read(self, resp):
        chunks, total = [], 0
        deadline = self.clock() + max(2.0, self.s.request_timeout)
        for chunk in resp.iter_content(8192):
            total += len(chunk)
            if total > self.s.max_bytes:
                break
            chunks.append(chunk)
            if self.clock() > deadline:
                break
        return b"".join(chunks)

    def _get(self, url):
        """Fetch one address. Every hop is checked, and redirects may not leave the site."""
        current = url
        for _ in range(self.s.max_redirects + 1):
            current = security.check_url(current, self.resolver)
            if site_key(current) != self.site:
                raise OffSiteRedirect(current)
            self._pause()
            timeout = max(1.0, min(self.s.request_timeout, self._remaining() + 2))
            resp = self.session.get(
                current, headers=self.headers, timeout=timeout, stream=True, allow_redirects=False
            )
            try:
                if resp.status_code in REDIRECTS:
                    location = resp.headers.get("Location")
                    if not location:
                        raise FetchError("redirect without a destination")
                    current = urljoin(current, location)
                    continue
                return Fetched(
                    status=resp.status_code,
                    url=current,
                    content_type=(resp.headers.get("Content-Type") or "").lower(),
                    data=self._read(resp),
                )
            finally:
                resp.close()
        raise FetchError("too many redirects")

    # -- robots.txt and sitemaps -------------------------------------------------

    def _load_robots(self):
        token = self.s.robots_token
        try:
            got = self._get(self.origin + "/robots.txt")
        except (FetchError, UnsafeURL, requests.RequestException):
            self.robots = Robots.unreachable(token)
            return
        if 500 <= got.status < 600:
            self.robots = Robots.unreachable(token)
        elif got.status == 200:
            text = got.data.decode("utf-8", errors="replace")
            self.robots = Robots.parse(text, token)
        else:
            self.robots = Robots(token)  # no robots.txt: everything is allowed
        if self.robots.delay:
            self.delay = min(max(self.delay, self.robots.delay), self.s.max_crawl_delay)

    def _load_sitemaps(self):
        pending = [u for u in self.robots.sitemaps if site_key(u) == self.site]
        if not pending:
            pending = [self.origin + "/sitemap.xml"]
        seen, files = set(), 0
        while pending and files < self.s.max_sitemap_files:
            url = pending.pop(0)
            if url in seen:
                continue
            seen.add(url)
            files += 1
            try:
                got = self._get(url)
            except (FetchError, UnsafeURL, requests.RequestException):
                continue
            if got.status != 200 or url.lower().endswith(".gz"):
                continue
            try:
                urls, sub = parse_sitemap(got.data)
            except Exception:
                continue
            for u in urls[: self.s.max_candidates]:
                link = clean_link(self.origin + "/", u)
                if link and site_key(link) == self.site:
                    self._add(link, None, depth=1)
            pending.extend(s for s in sub if site_key(s) == self.site)

    # -- candidates --------------------------------------------------------------

    def _add(self, url, anchor, depth):
        if site_key(url) != self.site or not self.robots.allowed(url):
            return
        doc = self.docs.get(url)
        if doc is None:
            if len(self.docs) >= self.s.max_candidates:
                return
            parts = urlsplit(url)
            if parts.query:
                seen = self._query_variants.get(parts.path, 0)
                if seen >= MAX_QUERY_VARIANTS:
                    return
                self._query_variants[parts.path] = seen + 1
            doc = Doc(url=url, depth=depth, kind=kind_of_url(url))
            self.docs[url] = doc
        else:
            doc.depth = min(doc.depth, depth)
        if anchor:
            doc.add_anchor(anchor)
        if doc.kind == "page" and url not in self.visited:
            priority = quick_score(self.query, url, doc.anchors) - 0.05 * doc.depth
            self.counter += 1
            heapq.heappush(self.frontier, (-priority, self.counter, url))

    # -- the search --------------------------------------------------------------

    def crawl(self, start_url):
        """Search the site. Yields a progress message after each page; see stop_reason after."""
        self.started = self.clock()
        start = security.check_url(start_url, self.resolver)
        self.site = site_key(start)
        parts = urlsplit(start)
        self.origin = f"{parts.scheme}://{parts.netloc}"

        yield {"type": "status", "message": "Checking the site's rules (robots.txt)..."}
        self._load_robots()
        if self.robots.disallow_all:
            self.stop_reason = "robots_unreachable"
            self.notes.append(
                "The site's robots.txt file could not be read, so I did not search it. Try again later."
            )
            return
        if not self.robots.allowed(start):
            self.stop_reason = "robots_blocked"
            self.notes.append("This site asks automated tools not to read that address, so I did not search it.")
            return

        yield {"type": "status", "message": "Looking for the site's page list (sitemap)..."}
        self._load_sitemaps()

        self._add(start, None, depth=0)
        if start in self.docs:
            self.counter += 1
            heapq.heappush(self.frontier, (float("-inf"), 0, start))  # the start page goes first
        yield {"type": "status", "message": "Reading pages..."}

        while self.frontier:
            if self.fetched >= self.s.max_pages:
                self.stop_reason = "page_limit"
                return
            if self._remaining() <= 0:
                self.stop_reason = "time_limit"
                return
            _, _, url = heapq.heappop(self.frontier)
            doc = self.docs.get(url)
            if doc is None or url in self.visited or doc.kind != "page":
                continue
            self.visited.add(url)
            try:
                got = self._get(url)
            except OffSiteRedirect as e:
                self.docs.pop(url, None)
                if url == start:
                    self.stop_reason = "start_redirect"
                    self.notes.append(
                        f"That address redirects to {urlsplit(e.url).netloc}. Search that address instead."
                    )
                    return
                self.failed += 1
                continue
            except (FetchError, UnsafeURL, requests.RequestException):
                self.docs.pop(url, None)
                self.failed += 1
                if url == start:
                    self.stop_reason = "start_failed"
                    self.notes.append("I could not open that website. Check the address and try again.")
                    return
                continue

            if got.url != url:  # a redirect within the site: keep one copy under the final address
                self.docs.pop(url, None)
                if got.url in self.visited or not self.robots.allowed(got.url):
                    continue
                self.visited.add(got.url)
                doc = self.docs.setdefault(got.url, Doc(url=got.url, depth=doc.depth, kind="page"))
            if not 200 <= got.status < 300:
                self.docs.pop(doc.url, None)
                self.failed += 1
                if url == start:
                    self.stop_reason = "start_failed"
                    self.notes.append(f"The website answered with an error (code {got.status}).")
                    return
                continue

            self.fetched += 1
            ctype = got.content_type
            if "html" not in ctype and "xml" not in ctype and ctype:
                doc.kind = "pdf" if "pdf" in ctype else "document"
                doc.fetched = True
            else:
                page = parse_html(got.data, got.url)
                doc.title = page["title"]
                doc.description = page["description"]
                doc.headings = page["headings"]
                doc.body = page["body"]
                doc.fetched = True
                for link, text in page["links"]:
                    self._add(link, text, depth=doc.depth + 1)
                if doc.url == start or url == start:
                    if len(page["body"]) < 200 and len(page["links"]) < 3 and page["scripts"] > 2:
                        self.notes.append(
                            "This site may build its pages with JavaScript, which I cannot read yet, "
                            "so the results may be incomplete."
                        )
            yield {"type": "progress", "pages": self.fetched, "limit": self.s.max_pages, "current": got.url}

        self.stop_reason = "done"

    def documents(self):
        return list(self.docs.values())
