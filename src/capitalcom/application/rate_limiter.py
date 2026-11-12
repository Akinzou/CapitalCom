"""Client-side throttling to Capital.com's published request limits."""

import bisect
import threading
from collections.abc import Mapping, Sequence
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
    first second; Capital.com counts per second, so the bucket drew 429s on bursts. Bookings
    may lie in the future and a new one may land before them: 2.0.0 booked in order, so a read
    queued up to a second behind trades that TRADE held back while GENERAL had room.
    Not thread-safe on its own; ``RateLimiter`` holds the lock.
    """

    def __init__(self, limit: int, window_s: float) -> None:
        if limit < 1:
            raise ValueError(f"a window needs a limit of at least 1 send, got {limit}")
        self._limit = limit
        self._window_s = window_s
        self._times: list[float] = []  # sorted

    def forget_before(self, now: float) -> None:
        """Drop bookings that no send at or after ``now`` can share a span with."""
        del self._times[: bisect.bisect_right(self._times, now - self._window_s)]

    def latest(self) -> float:
        """The latest booking, or minus infinity when there is none."""
        return self._times[-1] if self._times else float("-inf")

    def candidates(self, now: float) -> list[float]:
        """Where a free slot can begin: a booking, or a window after one."""
        return [t for s in self._times for t in (s, s + self._window_s) if t >= now]

    def fits(self, t: float) -> bool:
        """Whether a send at ``t`` keeps any ``limit + 1`` consecutive sends ``window_s`` apart."""
        times, n = self._times, self._limit
        at = bisect.bisect_right(times, t)

        def nth(i: int) -> float:
            # The bookings with ``t`` inserted at ``at``, read in place instead of copied.
            return times[i] if i < at else t if i == at else times[i - 1]

        # Only spans holding the new send can break. ``first + window_s <= last`` is the sum
        # this window's candidates are built from, so it never rejects a slot it produced.
        for first in range(max(0, at - n), min(at, len(times) - n) + 1):
            if nth(first) + self._window_s > nth(first + n):
                return False
        return True

    def record(self, t: float) -> None:
        """Count a send at ``t``."""
        bisect.insort(self._times, t)


def earliest(
    windows: Sequence[SlidingWindow], now: float, not_before: float | None = None
) -> float:
    """The earliest send time at or after ``now`` (and ``not_before``) every window allows.

    Out of order, one window's allowed times are no longer "from some point on", so the
    latest of the per-window answers could fail another window; every window's candidates are
    tried against all of them. A send a window after the latest booking always fits, so the
    search ends.
    """
    for window in windows:
        window.forget_before(now)
    floor = now if not_before is None else max(now, not_before)
    options = sorted({floor, *(t for window in windows for t in window.candidates(floor))})
    for t in options:
        if all(window.fits(t) for window in windows):
            return t
    raise AssertionError("unreachable: a window after the latest booking always fits")


_SESSION_PATH = "/api/v1/session"
_TRADE_PATHS = frozenset({"/api/v1/positions", "/api/v1/workingorders"})


def classify(method: str, path: str) -> frozenset[RequestKind]:
    """Return every limit a request counts against."""
    if method.upper() == "POST":
        if path == _SESSION_PATH:
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
            # Session calls keep their place: a logout or account switch that went before a
            # queued trade would leave it holding ended tokens or move it to the other account.
            # Every request counts in GENERAL, so its latest booking is the latest of all.
            not_before = max(w.latest() for w in windows) if path == _SESSION_PATH else None
            # The one time valid in every window is recorded in all of them, which keeps a login
            # delayed by SESSION counted in GENERAL when it is really sent.
            send_at = earliest(windows, now, not_before)
            for window in windows:
                window.record(send_at)
        # Sleeping outside the lock lets other threads book their own later times meanwhile.
        if send_at > now:
            self._clock.sleep(send_at - now)
