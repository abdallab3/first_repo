import unittest

from app.limiter import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RateLimiting(unittest.TestCase):
    def test_visitors_are_limited_inside_the_window_and_freed_after_it(self):
        clock = FakeClock()
        limiter = RateLimiter(3, 60, clock=clock)
        for _ in range(3):
            self.assertTrue(limiter.allow("a")[0])
        ok, wait = limiter.allow("a")
        self.assertFalse(ok)
        self.assertTrue(1 <= wait <= 61)
        self.assertTrue(limiter.allow("b")[0])  # someone else is not affected
        clock.now += 61
        self.assertTrue(limiter.allow("a")[0])

    def test_a_blocked_attempt_does_not_extend_the_wait(self):
        clock = FakeClock()
        limiter = RateLimiter(1, 60, clock=clock)
        self.assertTrue(limiter.allow("a")[0])
        for _ in range(10):
            clock.now += 5
            self.assertFalse(limiter.allow("a")[0])
        clock.now += 20
        self.assertTrue(limiter.allow("a")[0])


if __name__ == "__main__":
    unittest.main()
