"""Bookings out of order: a request takes the earliest slot every one of its windows allows."""

import random

import pytest

from capitalcom.application.rate_limiter import RateLimiter, RequestKind, SlidingWindow, classify
from tests.fakes import FrozenClock

LOGIN = ("POST", "/api/v1/session")
TRADE = ("POST", "/api/v1/positions")
READ = ("GET", "/api/v1/markets")


def _booked(limiter: RateLimiter, clock: FrozenClock, request: tuple[str, str]) -> float:
    """The send time ``request`` was given: now, plus the sleep it was told to take."""
    before = len(clock.sleeps)
    limiter.acquire(*request)
    return clock.monotonic() + (clock.sleeps[-1] if len(clock.sleeps) > before else 0.0)


def test_the_limiter_lets_a_read_past_a_login_held_back_by_session() -> None:
    # Through the client the read still waits, on the session lock, for the tokens that login
    # brings (ADR 0006); the limiter itself adds no wait.
    clock = FrozenClock()
    limiter = RateLimiter(clock)
    assert [_booked(limiter, clock, r) for r in (LOGIN, LOGIN, READ)] == [0.0, 1.0, 0.0]


def test_a_read_does_not_wait_behind_queued_trades() -> None:
    clock = FrozenClock()
    limiter = RateLimiter(clock)
    trades = [_booked(limiter, clock, TRADE) for _ in range(5)]
    assert trades == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.4])
    assert _booked(limiter, clock, READ) == 0.0


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_a_session_call_never_overtakes_a_booking(method: str) -> None:
    # A logout or account switch that went first would leave a queued trade holding ended
    # tokens, or move it to the other account.
    clock = FrozenClock()
    limiter = RateLimiter(clock)
    trades = [_booked(limiter, clock, TRADE) for _ in range(2)]
    assert _booked(limiter, clock, (method, "/api/v1/session")) >= trades[-1]


def test_a_window_needs_room_for_one_send() -> None:
    with pytest.raises(ValueError, match="limit"):
        SlidingWindow(0, 1.0)


def test_a_full_general_window_still_waits() -> None:
    clock = FrozenClock()
    limiter = RateLimiter(clock)
    sends = [_booked(limiter, clock, READ) for _ in range(11)]
    assert sends == [0.0] * 10 + [1.0]


def test_a_trade_burst_keeps_a_tenth_apart_despite_float_sums() -> None:
    # A slot found as booking + 0.1 must pass the check it was found by; were it rejected by
    # float rounding, the next candidate would sit a further tenth away.
    clock = FrozenClock()
    limiter = RateLimiter(clock)
    sends = [_booked(limiter, clock, TRADE) for _ in range(12)]
    assert sends == pytest.approx([i / 10 for i in range(12)], abs=1e-9)


_LIMITS = {RequestKind.GENERAL: (3, 4), RequestKind.TRADE: (1, 2), RequestKind.SESSION: (1, 3)}
LOGOUT = ("DELETE", "/api/v1/session")


def _oracle(history: dict[RequestKind, list[int]], request: tuple[str, str], now: int) -> int:
    """Earliest whole second at or after ``now`` that leaves no window over its limit.

    Counts sends in every window-long span, instead of the limiter's spans between bookings.
    A session call also waits for every booking, since every request counts in GENERAL.
    """
    kinds = classify(*request)
    if request[1] == "/api/v1/session":
        now = max([now, *history[RequestKind.GENERAL]])

    def allowed(t: int) -> bool:
        for kind in kinds:
            limit, span = _LIMITS[kind]
            times = [*history[kind], t]
            if any(sum(start <= x < start + span for x in times) > limit for start in times):
                return False
        return True

    return next(t for t in range(now, now + 1000) if allowed(t))


@pytest.mark.parametrize("seed", range(200))
def test_random_interleavings_match_a_brute_force_search(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - a reproducible schedule, not a secret
    clock = FrozenClock()
    windows = {kind: SlidingWindow(*_LIMITS[kind]) for kind in RequestKind}
    limiter = RateLimiter(clock, windows)
    history: dict[RequestKind, list[int]] = {kind: [] for kind in RequestKind}
    for _ in range(25):
        clock.advance(rng.choice([0, 0, 1, 2]))
        request = rng.choice([LOGIN, LOGOUT, TRADE, TRADE, READ, READ, READ])
        now = int(clock.monotonic())
        expected = _oracle(history, request, now)
        assert _booked(limiter, clock, request) == expected
        for kind in classify(*request):
            history[kind].append(expected)
