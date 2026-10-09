import unittest

from app.crawler import Robots

TOKEN = "websitenavigatorbot"


def parse(text):
    return Robots.parse(text, TOKEN)


class RobotsRules(unittest.TestCase):
    def test_simple_disallow(self):
        r = parse("User-agent: *\nDisallow: /private/\n")
        self.assertFalse(r.allowed("https://s.example/private/page"))
        self.assertTrue(r.allowed("https://s.example/public"))
        self.assertTrue(r.allowed("https://s.example/privateer"))

    def test_wildcards_and_end_anchor(self):
        r = parse("User-agent: *\nDisallow: /*?print=\nDisallow: /*.pdf$\n")
        self.assertFalse(r.allowed("https://s.example/a?print=1"))
        self.assertFalse(r.allowed("https://s.example/files/x.pdf"))
        self.assertTrue(r.allowed("https://s.example/files/x.pdf?download=1"))
        self.assertTrue(r.allowed("https://s.example/a?page=2"))

    def test_longest_rule_wins_and_allow_wins_ties(self):
        r = parse("User-agent: *\nDisallow: /private/\nAllow: /private/public/\n")
        self.assertTrue(r.allowed("https://s.example/private/public/x"))
        self.assertFalse(r.allowed("https://s.example/private/secret"))
        tie = parse("User-agent: *\nDisallow: /a\nAllow: /a\n")
        self.assertTrue(tie.allowed("https://s.example/a"))

    def test_empty_disallow_allows_everything(self):
        r = parse("User-agent: *\nDisallow:\n")
        self.assertTrue(r.allowed("https://s.example/anything"))

    def test_our_own_group_beats_the_star_group(self):
        r = parse("User-agent: *\nDisallow: /\n\nUser-agent: WebsiteNavigatorBot\nDisallow: /admin/\n")
        self.assertTrue(r.allowed("https://s.example/calendar"))
        self.assertFalse(r.allowed("https://s.example/admin/x"))

    def test_other_bots_rules_do_not_apply_to_us(self):
        r = parse("User-agent: SomeOtherBot\nDisallow: /\n")
        self.assertTrue(r.allowed("https://s.example/calendar"))

    def test_block_everything(self):
        r = parse("User-agent: *\nDisallow: /\n")
        self.assertFalse(r.allowed("https://s.example/"))
        self.assertFalse(r.allowed("https://s.example/calendar"))

    def test_several_user_agent_lines_share_one_group(self):
        r = parse("User-agent: A\nUser-agent: *\nDisallow: /x\n")
        self.assertFalse(r.allowed("https://s.example/x"))

    def test_comments_crawl_delay_and_sitemaps(self):
        r = parse(
            "# hello\nUser-agent: * # everyone\nCrawl-delay: 3\nDisallow: /tmp # temp\n"
            "Sitemap: https://s.example/sitemap.xml\n"
        )
        self.assertEqual(r.delay, 3.0)
        self.assertFalse(r.allowed("https://s.example/tmp/x"))
        self.assertEqual(r.sitemaps, ["https://s.example/sitemap.xml"])

    def test_unreachable_robots_means_do_not_crawl(self):
        r = Robots.unreachable(TOKEN)
        self.assertFalse(r.allowed("https://s.example/"))

    def test_robots_txt_itself_is_always_readable(self):
        r = parse("User-agent: *\nDisallow: /\n")
        self.assertTrue(r.allowed("https://s.example/robots.txt"))

    def test_garbage_does_not_crash(self):
        r = parse("\x00\x01 not a robots file\n::::\nDisallow\nUser-agent\n")
        self.assertTrue(r.allowed("https://s.example/anything"))


if __name__ == "__main__":
    unittest.main()
