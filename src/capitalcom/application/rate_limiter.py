"""Client-side throttling to Capital.com's published request limits."""

import threading
from collections.abc import Mapping
from enum import Enum

from capitalcom.application.ports import Clock


class RequestKind(Enum):
    """Limit classes from Capital.com's API documentation."""

    GENERAL = "GENERAL"
    TRADE = "TRADE"
    SESSION = "SESSION"


class TokenBucket:
    """Token bucket that hands out future slots instead of refusing.

    The token count may go negative: each negative token is a slot already promised to a
    waiting caller, so concurrent callers queue in order rather than all waking at once.
    Not thread-safe on its own; ``RateLimiter`` holds the lock.
    """

    def __init__(self, rate_per_s: float, capacity: int) -> None:
        self._rate = rate_per_s
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._last: float | None = None

    def reserve(self, now: float) -> float:
        """Take one token and return how many seconds the caller must wait for it."""
        if self._last is not None and now > self._last:
            self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
        self._last = now if self._last is None else max(self._last, now)
        self._tokens -= 1
        return 0.0 if self._tokens >= 0 else -self._tokens / self._rate


_TRADE_PATHS = frozenset({"/api/v1/positions", "/api/v1/workingorders"})


def classify(method: str, path: str) -> frozenset[RequestKind]:
    """Return every limit a request counts against."""
    if method.upper() == "POST":
        if path == "/api/v1/session":
            return frozenset({RequestKind.GENERAL, RequestKind.SESSION})
        if path in _TRADE_PATHS:
            return frozenset({RequestKind.GENERAL, RequestKind.TRADE})
    return frozenset({RequestKind.GENERAL})


def default_buckets() -> dict[RequestKind, TokenBucket]:
    """10 requests/s overall, one trade per 0.1 s, one session creation per second."""
    return {
        RequestKind.GENERAL: TokenBucket(10, 10),
        RequestKind.TRADE: TokenBucket(10, 1),
        RequestKind.SESSION: TokenBucket(1, 1),
    }


class RateLimiter:
    """Blocks the calling thread until a request may be sent."""

    def __init__(
        self, clock: Clock, buckets: Mapping[RequestKind, TokenBucket] | None = None
    ) -> None:
        self._clock = clock
        self._buckets = dict(buckets) if buckets is not None else default_buckets()
        self._lock = threading.Lock()

    def acquire(self, method: str, path: str) -> None:
        """Reserve a slot in every applicable bucket, then sleep until the latest one."""
        with self._lock:
            now = self._clock.monotonic()
            wait = max(self._buckets[kind].reserve(now) for kind in classify(method, path))
        # Sleeping outside the lock lets other threads reserve their own later slots meanwhile.
        if wait > 0:
            self._clock.sleep(wait)
