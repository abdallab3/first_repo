import unittest

from app.ranking import Doc, kind_of_url, parse_query, quick_score, rank, stem, years_in


def doc(url, title="", anchors=(), headings=(), body="", depth=1, fetched=True):
    d = Doc(url=url, title=title, headings=list(headings), body=body, depth=depth, fetched=fetched, kind=kind_of_url(url))
    for a in anchors:
        d.add_anchor(a)
    return d


class QueryParsing(unittest.TestCase):
    def test_filler_words_are_dropped_and_years_are_kept_apart(self):
        q = parse_query("find the 2026 school calendar subpage")
        self.assertEqual(q.terms, ["school", "calendar"])
        self.assertEqual(q.years, {2026})

    def test_school_year_ranges_count_as_both_years(self):
        self.assertEqual(parse_query("calendar 2025-26").years, {2025, 2026})
        self.assertEqual(parse_query("calendar 2025/2026").years, {2025, 2026})
        self.assertEqual(years_in("2026-27 District Calendar"), {2026, 2027})
        self.assertEqual(years_in("SchoolCalendar2026.pdf"), {2026})

    def test_empty_or_filler_only_requests_are_rejected(self):
        for text in ["", "   ", "find the page", "show me the website"]:
            with self.assertRaises(ValueError, msg=text):
                parse_query(text)

    def test_a_year_alone_is_enough(self):
        q = parse_query("2026")
        self.assertEqual((q.terms, q.years), ([], {2026}))

    def test_very_long_requests_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_query("calendar " * 100)

    def test_word_shortening(self):
        self.assertEqual(stem("dates"), stem("date"))
        self.assertEqual(stem("hiring"), stem("hire"))
        self.assertEqual(stem("policies"), stem("policy"))
        self.assertEqual(stem("Calendars"), stem("calendar"))
        self.assertEqual(stem("meetings"), stem("meeting"))
        self.assertEqual(stem("bus"), "bus")


class Ranking(unittest.TestCase):
    def setUp(self):
        self.docs = [
            doc("https://s.example/calendar/2024-2025", "2024-2025 School Calendar", ["2024-2025 School Calendar"]),
            doc("https://s.example/calendar/2026-2027", "2026-2027 School Calendar", ["2026-2027 School Calendar"]),
            doc("https://s.example/lunch", "Lunch Menu", ["Lunch Menu"], body="school lunch prices"),
            doc("https://s.example/about", "About us", ["About"], body="our school calendar is online"),
        ]

    def test_the_matching_year_wins(self):
        best = rank(parse_query("2026 school calendar"), self.docs)[0]
        self.assertTrue(best["url"].endswith("2026-2027"))
        self.assertEqual(best["strength"], "strong")
        best = rank(parse_query("the 2024 school calendar"), self.docs)[0]
        self.assertTrue(best["url"].endswith("2024-2025"))

    def test_without_a_year_both_calendars_rank_above_unrelated_pages(self):
        urls = [r["url"] for r in rank(parse_query("school calendar"), self.docs)]
        self.assertEqual(set(urls[:2]), {self.docs[0].url, self.docs[1].url})

    def test_related_words_match(self):
        docs = [doc("https://s.example/schedule", "Bell Schedule", ["Bell Schedule"]), doc("https://s.example/x", "Other")]
        best = rank(parse_query("calendar"), docs)[0]
        self.assertTrue(best["url"].endswith("/schedule"))

    def test_a_page_matching_every_word_beats_one_matching_a_single_word(self):
        docs = [
            doc("https://s.example/a", "Calendar", ["Calendar"]),
            doc("https://s.example/b", "Lunch calendar for parents", ["Lunch calendar for parents"]),
        ]
        best = rank(parse_query("parents lunch calendar"), docs)[0]
        self.assertTrue(best["url"].endswith("/b"))

    def test_documents_are_found_by_file_name_alone(self):
        docs = [
            doc("https://s.example/files/Parent_Handbook_2026.pdf", fetched=False),
            doc("https://s.example/files/SchoolCalendar2026.pdf", fetched=False),
            doc("https://s.example/files/budget.pdf", fetched=False),
        ]
        r = rank(parse_query("2026 school calendar"), docs)[0]
        self.assertTrue(r["url"].endswith("SchoolCalendar2026.pdf"))
        self.assertEqual(r["kind"], "pdf")

    def test_a_wrong_year_is_pushed_down(self):
        docs = [
            doc("https://s.example/old", "School Calendar 2019", ["School Calendar 2019"]),
            doc("https://s.example/new", "School Calendar", ["School Calendar"]),
        ]
        best = rank(parse_query("2026 school calendar"), docs)[0]
        self.assertTrue(best["url"].endswith("/new"))

    def test_results_explain_themselves(self):
        best = rank(parse_query("2026 school calendar"), self.docs)[0]
        text = " ".join(best["reasons"])
        self.assertIn("Link text", text)
        self.assertIn("2026", text)
        self.assertEqual(best["missing"], [])

    def test_pages_with_no_match_are_left_out(self):
        self.assertEqual(rank(parse_query("zebra crossing"), self.docs), [])
        self.assertEqual(rank(parse_query("calendar"), []), [])

    def test_missing_words_are_reported(self):
        docs = [doc("https://s.example/c", "Calendar", ["Calendar"])]
        r = rank(parse_query("district calendar"), docs)[0]
        self.assertEqual(r["missing"], ["district"])
        self.assertEqual(r["strength"], "possible")

    def test_quick_score_prefers_promising_links(self):
        q = parse_query("2026 school calendar")
        good = quick_score(q, "https://s.example/calendar/2026", ["School Calendar"])
        bad = quick_score(q, "https://s.example/lunch", ["Lunch"])
        old = quick_score(q, "https://s.example/calendar/2019", ["School Calendar"])
        self.assertGreater(good, old)
        self.assertGreater(old, bad)


if __name__ == "__main__":
    unittest.main()
