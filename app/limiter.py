"""Limits on how much one visitor, and the whole server, can search at once."""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Allow `limit` searches per visitor in any `window` seconds."""

    def __init__(self, limit, window, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key):
        """Return (allowed, seconds_to_wait)."""
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(1, int(self.window - (now - hits[0])) + 1)
            hits.append(now)
            # Forget visitors who have gone quiet so memory does not grow forever.
            if len(self._hits) > 5000:
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
                    del self._hits[k]
            return True, 0


class ConcurrencyGate:
    """Cap the number of searches running at the same moment."""

    def __init__(self, limit):
        self._sem = threading.BoundedSemaphore(limit)

    def try_enter(self):
        return self._sem.acquire(blocking=False)

    def leave(self):
        self._sem.release()
