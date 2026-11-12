"""Client-side throttling to Capital.com's published request limits."""

import threading
from collections import deque
from collections.abc import Mapping
from enum import Enum

from capitalcom.application.ports import Clock


class RequestKind(Enum):
    """Limit classes from Capital.com's API documentation."""

    GENERAL = "GENERAL"
    TRADE = "TRADE"
    SESSION = "SESSION"


class SlidingWindow:
    """At most ``limit`` sends inside any ``window_s`` span, counted at send time.

    A token bucket of capacity N refilling at N/s lets almost 2N requests through in the
    first second; Capital.com counts per second, so the bucket drew 429s on bursts. Send
    times are recorded in non-decreasing order, so callers keep their FIFO order per window.
    Not thread-safe on its own; ``RateLimiter`` holds the lock.
    """

    def __init__(self, limit: int, window_s: float) -> None:
        self._window_s = window_s
        self._times: deque[float] = deque(maxlen=limit)

    def earliest(self, t: float) -> float:
        """Earliest send time at or after ``t`` that keeps this window within its limit."""
        if not self._times:
            return t
        t = max(t, self._times[-1])
        if len(self._times) == self._times.maxlen:
            t = max(t, self._times[0] + self._window_s)
        return t

    def record(self, t: float) -> None:
        """Count a send at ``t``; the oldest send falls out once the window is full."""
        self._times.append(t)


_TRADE_PATHS = frozenset({"/api/v1/positions", "/api/v1/workingorders"})


def classify(method: str, path: str) -> frozenset[RequestKind]:
    """Return every limit a request counts against."""
    if method.upper() == "POST":
        if path == "/api/v1/session":
            return frozenset({RequestKind.GENERAL, RequestKind.SESSION})
        if path in _TRADE_PATHS:
            return frozenset({RequestKind.GENERAL, RequestKind.TRADE})
    return frozenset({RequestKind.GENERAL})


def default_windows() -> dict[RequestKind, SlidingWindow]:
    """10 requests per second overall, one trade per 0.1 s, one session creation per second."""
    return {
        RequestKind.GENERAL: SlidingWindow(10, 1.0),
        RequestKind.TRADE: SlidingWindow(1, 0.1),
        RequestKind.SESSION: SlidingWindow(1, 1.0),
    }


class RateLimiter:
    """Blocks the calling thread until a request may be sent."""

    def __init__(
        self, clock: Clock, windows: Mapping[RequestKind, SlidingWindow] | None = None
    ) -> None:
        self._clock = clock
        self._windows = dict(windows) if windows is not None else default_windows()
        self._lock = threading.Lock()

    def acquire(self, method: str, path: str) -> None:
        """Book one send time valid in every applicable window, then sleep until it."""
        with self._lock:
            now = self._clock.monotonic()
            windows = [self._windows[kind] for kind in classify(method, path)]
            # Each window answers max(t, its own bound), so the latest answer is valid in every
            # window at once. That same time is recorded in all of them, which keeps a login
            # delayed by SESSION counted in GENERAL when it is really sent.
            send_at = max(w.earliest(now) for w in windows)
            for window in windows:
                window.record(send_at)
        # Sleeping outside the lock lets other threads book their own later times meanwhile.
        if send_at > now:
            self._clock.sleep(send_at - now)
