import unittest

from app import security
from app.security import UnsafeURL, check_url, is_public_ip, site_key
from tests.fakesite import public_resolver


class BlockedAddresses(unittest.TestCase):
    def assert_blocked(self, url):
        with self.assertRaises(UnsafeURL, msg=url):
            check_url(url, public_resolver)

    def test_private_and_internal_addresses_are_refused(self):
        for url in [
            "http://127.0.0.1/",
            "http://127.1.2.3:80/",
            "http://localhost/",
            "http://LOCALHOST./",
            "http://10.0.0.5/",
            "http://172.16.0.1/",
            "http://192.168.1.1/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://[fe80::1]/",
            "http://[fd00::1]/",
            "http://0.0.0.0/",
            "http://100.64.0.1/",
            "http://[::ffff:127.0.0.1]/",
            "http://[::ffff:10.0.0.1]/",
            "http://[64:ff9b::a00:1]/",
            "http://[2002:a00:1::]/",
            "http://224.0.0.1/",
            "http://private.example/",
            "http://metadata.example/",
            "http://db.railway.internal/",
            "http://printer.local/",
            "http://service.localhost/",
        ]:
            self.assert_blocked(url)

    def test_other_schemes_ports_and_logins_are_refused(self):
        for url in [
            "ftp://school.example/",
            "file:///etc/passwd",
            "gopher://school.example/",
            "javascript:alert(1)",
            "http://school.example:22/",
            "http://school.example:6379/",
            "http://user:secret@school.example/",
            "http://school.example:abc/",
            "",
            "   ",
            "http://" + "a" * 3000 + ".example/",
        ]:
            self.assert_blocked(url)

    def test_a_name_with_any_private_address_is_refused(self):
        def mixed(host):
            return ["93.184.216.34", "10.0.0.5"]

        with self.assertRaises(UnsafeURL):
            check_url("https://school.example/", mixed)

    def test_a_name_that_does_not_resolve_is_refused(self):
        def nothing(host):
            return []

        with self.assertRaises(UnsafeURL):
            check_url("https://school.example/", nothing)

    def test_decimal_and_octal_tricks_are_refused_with_the_real_resolver(self):
        for url in ["http://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/", "http://127.0.0.1./"]:
            with self.assertRaises(UnsafeURL, msg=url):
                check_url(url)  # uses the real system resolver


class AllowedAddresses(unittest.TestCase):
    def test_plain_names_get_https_and_are_tidied(self):
        self.assertEqual(check_url("school.example", public_resolver), "https://school.example/")
        self.assertEqual(
            check_url("  http://School.Example/Path?q=1#frag ", public_resolver),
            "http://school.example/Path?q=1",
        )
        self.assertEqual(check_url("https://school.example:443/a", public_resolver), "https://school.example:443/a")

    def test_public_ip_addresses_are_allowed(self):
        self.assertEqual(check_url("http://93.184.216.34/", public_resolver), "http://93.184.216.34/")
        self.assertTrue(is_public_ip("8.8.8.8"))
        self.assertTrue(is_public_ip("2606:4700:4700::1111"))

    def test_private_ranges_are_not_public(self):
        for ip in ["10.1.2.3", "127.0.0.1", "169.254.1.1", "::1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "not-an-ip"]:
            self.assertFalse(is_public_ip(ip), ip)


class SiteKey(unittest.TestCase):
    def test_www_is_ignored(self):
        self.assertEqual(site_key("https://www.school.example/a"), site_key("http://school.example/b"))
        self.assertNotEqual(site_key("https://school.example/"), site_key("https://other.example/"))
        self.assertNotEqual(site_key("https://school.example/"), site_key("https://evil.school.example.attacker.test/"))


if __name__ == "__main__":
    unittest.main()
