"""A small sliding-window rate limiter for sensitive endpoints (sign-in, invitations).

It counts in this process's memory. With several workers or servers each keeps
its own counts, so put a shared store such as Redis behind the same `check`
before scaling out.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float) -> None:
        """Counts one attempt for `key`; 429 if there were already `limit` in `window` seconds."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = int(hits[0] + window - now) + 1
                raise HTTPException(
                    429, "too many attempts, try again later", {"Retry-After": str(retry_after)}
                )
            hits.append(now)
            if len(self._hits) > 10_000:  # forget keys that have gone quiet
                for quiet in [k for k, v in self._hits.items() if not v or v[-1] <= now - 3600]:
                    del self._hits[quiet]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
