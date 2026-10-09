import copy
import unittest

from app.config import Settings
from app.search import run_search
from tests.fakesite import PAGES, REDIRECTS, FakeAdapter, fake_session, public_resolver

START = "https://school.example/"


def search(request, start=START, settings=None, pages=None, redirects=None, clock=None, sleep=None):
    settings = settings or Settings(request_delay=0, max_seconds=60)
    adapter = FakeAdapter(pages=pages, redirects=redirects)
    session = fake_session(adapter)
    kwargs = {}
    if clock:
        kwargs["clock"] = clock
    events = list(
        run_search(start, request, session, settings, resolver=public_resolver, sleep=sleep or (lambda s: None), **kwargs)
    )
    return events, adapter


def final(events):
    return events[-1]


class FindingPages(unittest.TestCase):
    def test_finds_the_2026_calendar_page(self):
        events, _ = search("find the 2026 school calendar subpage")
        result = final(events)
        self.assertEqual(result["type"], "results")
        self.assertEqual(result["best"]["url"], "https://school.example/calendar/2026-2027")
        self.assertEqual(result["best"]["strength"], "strong")
        self.assertLessEqual(len(result["others"]), 3)

    def test_the_year_decides_between_calendars(self):
        events, _ = search("2024 school calendar")
        self.assertEqual(final(events)["best"]["url"], "https://school.example/calendar/2024-2025")

    def test_finds_a_pdf_without_downloading_it(self):
        events, adapter = search("district calendar pdf 2026")
        best = final(events)["best"]
        self.assertEqual(best["kind"], "pdf")
        self.assertTrue(best["url"].endswith("2026-27_district_calendar.pdf"))
        self.assertFalse([u for u in adapter.requested if u.endswith(".pdf")])

    def test_finds_the_parent_handbook_pdf(self):
        events, _ = search("parent handbook")
        self.assertTrue(final(events)["best"]["url"].endswith("parent_handbook.pdf"))

    def test_finds_the_concerns_section_for_parents(self):
        events, _ = search("report a concern")
        self.assertEqual(final(events)["best"]["url"], "https://school.example/parents/report-a-concern")
        events, _ = search("concerns for parents")
        self.assertIn("/parents", final(events)["best"]["url"])

    def test_the_home_page_is_not_offered_as_an_answer(self):
        events, _ = search("school")
        urls = [final(events)["best"]["url"]] + [o["url"] for o in final(events)["others"]]
        self.assertNotIn(START, urls)

    def test_pages_only_listed_in_the_sitemap_are_found(self):
        pages = copy.deepcopy(PAGES)
        pages["/hidden-treasure"] = (
            200, "text/html", "<html><head><title>Hidden treasure</title></head><body>Gold</body></html>"
        )
        pages["/sitemap.xml"] = (
            200,
            "application/xml",
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://school.example/hidden-treasure</loc></url></urlset>",
        )
        events, _ = search("hidden treasure", pages=pages)
        self.assertEqual(final(events)["best"]["url"], "https://school.example/hidden-treasure")

    def test_no_match_gives_an_honest_answer(self):
        events, _ = search("zebra crossing permit")
        result = final(events)
        self.assertIsNone(result["best"])
        self.assertIn("did not find", result["message"])

    def test_progress_is_reported_along_the_way(self):
        events, _ = search("school calendar")
        kinds = [e["type"] for e in events]
        self.assertIn("status", kinds)
        self.assertIn("progress", kinds)
        self.assertEqual(kinds[-1], "results")
        pages = [e["pages"] for e in events if e["type"] == "progress"]
        self.assertEqual(pages, sorted(pages))


class Politeness(unittest.TestCase):
    def test_pages_blocked_by_robots_txt_are_never_requested_or_shown(self):
        events, adapter = search("staff calendar 2026")
        self.assertFalse([u for u in adapter.requested if "/private/" in u])
        shown = [final(events)["best"]] + final(events)["others"] if final(events)["best"] else []
        self.assertFalse([r for r in shown if "/private/" in r["url"]])

    def test_a_site_that_blocks_everyone_is_not_searched(self):
        pages = copy.deepcopy(PAGES)
        pages["/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /\n")
        events, adapter = search("calendar", pages=pages)
        self.assertEqual(final(events)["type"], "error")
        self.assertIn("asks automated tools", final(events)["message"])
        self.assertEqual([u for u in adapter.requested if not u.endswith("/robots.txt")], [])

    def test_an_unreadable_robots_file_stops_the_search(self):
        pages = copy.deepcopy(PAGES)
        pages["/robots.txt"] = (503, "text/plain", "busy")
        events, adapter = search("calendar", pages=pages)
        self.assertEqual(final(events)["type"], "error")
        self.assertIn("robots.txt", final(events)["message"])
        self.assertEqual([u for u in adapter.requested if not u.endswith("/robots.txt")], [])

    def test_a_missing_robots_file_means_everything_is_allowed(self):
        pages = {k: v for k, v in PAGES.items() if k != "/robots.txt"}
        events, _ = search("2026 school calendar", pages=pages)
        self.assertEqual(final(events)["best"]["url"], "https://school.example/calendar/2026-2027")

    def test_crawl_delay_is_honored_but_capped(self):
        pages = copy.deepcopy(PAGES)
        pages["/robots.txt"] = (200, "text/plain", "User-agent: *\nCrawl-delay: 2\n")
        slept = []
        search("school calendar", pages=pages, sleep=slept.append, settings=Settings(request_delay=0.1, max_seconds=60))
        self.assertTrue(any(s > 1.5 for s in slept), slept)
        pages["/robots.txt"] = (200, "text/plain", "User-agent: *\nCrawl-delay: 600\n")
        slept.clear()
        search("school calendar", pages=pages, sleep=slept.append, settings=Settings(request_delay=0.1, max_seconds=60))
        self.assertTrue(slept and max(slept) <= 5.0, slept)

    def test_the_crawler_says_who_it_is(self):
        events, adapter = search("calendar")
        self.assertTrue(adapter.user_agents)
        self.assertTrue(all("WebsiteNavigatorBot" in ua for ua in adapter.user_agents), adapter.user_agents)


class Limits(unittest.TestCase):
    def test_the_page_limit_is_respected(self):
        events, _ = search("school", settings=Settings(request_delay=0, max_pages=2, max_seconds=60))
        result = final(events)
        self.assertLessEqual(result["pages_checked"], 2)
        self.assertEqual(result["stopped"], "page_limit")

    def test_the_time_limit_is_respected(self):
        ticks = {"now": 0.0}

        def clock():
            ticks["now"] += 10.0
            return ticks["now"]

        events, _ = search("school", settings=Settings(request_delay=0, max_seconds=25), clock=clock)
        self.assertEqual(final(events)["stopped"], "time_limit")

    def test_a_broken_page_is_skipped_and_the_search_goes_on(self):
        events, _ = search("2026 school calendar")
        result = final(events)
        self.assertEqual(result["best"]["url"], "https://school.example/calendar/2026-2027")
        self.assertTrue(any("could not be read" in n for n in result["notes"]))

    def test_a_failing_start_page_is_reported(self):
        pages = copy.deepcopy(PAGES)
        pages["/"] = (500, "text/html", "oops")
        events, _ = search("calendar", pages=pages)
        self.assertEqual(final(events)["type"], "error")
        self.assertIn("error", final(events)["message"])

    def test_sites_that_need_javascript_get_a_warning(self):
        pages = {
            "/": (
                200,
                "text/html",
                '<html><body><div id="app"></div><script src="a.js"></script><script src="b.js"></script>'
                '<script>x()</script></body></html>',
            )
        }
        events, _ = search("calendar", pages=pages)
        result = final(events)
        self.assertIsNone(result["best"])
        self.assertTrue(any("JavaScript" in n for n in result["notes"]))


class StayingSafe(unittest.TestCase):
    def test_redirects_to_other_websites_are_not_followed(self):
        events, adapter = search("school calendar")
        self.assertFalse([u for u in adapter.requested if "evil.example" in u])

    def test_redirects_to_private_addresses_are_not_followed(self):
        events, adapter = search("school calendar")
        self.assertFalse([u for u in adapter.requested if "169.254.169.254" in u])

    def test_links_to_other_websites_are_ignored(self):
        events, adapter = search("other site calendar")
        self.assertFalse([u for u in adapter.requested if "other.example" in u])

    def test_a_start_address_that_redirects_to_another_site_is_explained(self):
        events, _ = search("calendar", redirects={"/": "https://other.example/"})
        self.assertEqual(final(events)["type"], "error")
        self.assertIn("other.example", final(events)["message"])

    def test_private_start_addresses_are_refused_before_anything_is_requested(self):
        for start in ["http://127.0.0.1/", "http://10.0.0.5/", "http://private.example/", "http://metadata.example/"]:
            events, adapter = search("calendar", start=start)
            self.assertEqual(final(events)["type"], "error", start)
            self.assertEqual(adapter.requested, [], start)

    def test_a_request_with_nothing_to_find_is_rejected(self):
        with self.assertRaises(ValueError):
            search("find the page")


if __name__ == "__main__":
    unittest.main()
