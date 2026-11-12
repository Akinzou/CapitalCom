import threading
from datetime import timedelta
from email.utils import format_datetime

import pytest

from capitalcom.application.rate_limiter import (
    RateLimiter,
    RequestKind,
    SlidingWindow,
    classify,
    earliest,
)
from capitalcom.application.retry import (
    RetryPolicy,
    backoff_delay,
    is_retry_safe,
    parse_retry_after,
)
from tests.fakes import EPOCH, FakeClock, FrozenClock


def test_retry_after_delta_seconds() -> None:
    assert parse_retry_after("2", EPOCH) == 2.0


def test_retry_after_http_date_in_future() -> None:
    value = format_datetime(EPOCH + timedelta(seconds=3), usegmt=True)
    assert parse_retry_after(value, EPOCH) == pytest.approx(3.0)


def test_retry_after_http_date_in_past_is_zero() -> None:
    value = format_datetime(EPOCH - timedelta(seconds=30), usegmt=True)
    assert parse_retry_after(value, EPOCH) == 0.0


@pytest.mark.parametrize("value", ["soon", None, "", "-5", "nan", "inf", "²", "٣"])
def test_retry_after_garbage_is_none(value: str | None) -> None:
    assert parse_retry_after(value, EPOCH) is None


def test_backoff_is_capped_at_max_delay() -> None:
    assert backoff_delay(RetryPolicy(), 10, None, lambda: 1.0) == 8.0


def test_backoff_uses_equal_jitter() -> None:
    policy = RetryPolicy()
    assert backoff_delay(policy, 1, None, lambda: 0.0) == pytest.approx(0.5)
    assert backoff_delay(policy, 1, None, lambda: 1.0) == pytest.approx(1.0)


def test_backoff_prefers_retry_after_capped_at_a_minute() -> None:
    assert backoff_delay(RetryPolicy(), 0, 2.0, lambda: 0.0) == 2.0
    assert backoff_delay(RetryPolicy(), 0, 3600.0, lambda: 0.0) == 60.0


def test_only_reads_and_session_calls_are_retry_safe() -> None:
    assert is_retry_safe("GET", "/api/v1/positions")
    assert is_retry_safe("POST", "/api/v1/session")
    assert is_retry_safe("DELETE", "/api/v1/session")
    assert not any(is_retry_safe(m, "/api/v1/positions") for m in ("POST", "PUT", "DELETE"))


def test_classify() -> None:
    assert classify("POST", "/api/v1/session") == {RequestKind.GENERAL, RequestKind.SESSION}
    assert classify("POST", "/api/v1/positions") == {RequestKind.GENERAL, RequestKind.TRADE}
    assert classify("POST", "/api/v1/workingorders") == {RequestKind.GENERAL, RequestKind.TRADE}
    assert classify("GET", "/api/v1/positions") == {RequestKind.GENERAL}
    assert classify("PUT", "/api/v1/session") == {RequestKind.GENERAL}


def test_sliding_window_frees_a_slot_when_the_oldest_send_leaves() -> None:
    window = SlidingWindow(2, 1.0)
    assert earliest([window], 0.0) == 0.0
    window.record(0.0)
    window.record(0.5)
    assert earliest([window], 0.6) == 1.0
    window.record(1.0)
    assert earliest([window], 1.2) == 1.5


def test_a_free_slot_before_a_later_booking_is_taken() -> None:
    # 2.0.0 queued behind the booking at 3.0, so a read waited for a login held back by SESSION.
    window = SlidingWindow(5, 1.0)
    window.record(3.0)
    assert earliest([window], 1.0) == 1.0


def test_a_slot_that_would_crowd_a_later_booking_is_not_taken() -> None:
    window = SlidingWindow(1, 1.0)
    window.record(3.0)
    assert earliest([window], 2.5) == 4.0


def test_eleventh_general_request_waits_a_full_second() -> None:
    # A bucket refilling at 10/s let the eleventh request out after 0.1 s: 11 in one second.
    clock = FakeClock()
    limiter = RateLimiter(clock)
    for _ in range(11):
        limiter.acquire("GET", "/api/v1/markets")
    assert clock.sleeps == [pytest.approx(1.0)]


_WINDOWS = {
    RequestKind.GENERAL: (10, 1.0),
    RequestKind.SESSION: (1, 1.0),
    RequestKind.TRADE: (1, 0.1),
}


def _send_all(requests: list[tuple[str, str]]) -> list[tuple[float, frozenset[RequestKind]]]:
    clock = FakeClock()
    limiter = RateLimiter(clock)
    sends = []
    for method, path in requests:
        limiter.acquire(method, path)
        sends.append((clock.monotonic(), classify(method, path)))
    return sends


def _assert_no_window_exceeded(sends: list[tuple[float, frozenset[RequestKind]]]) -> None:
    for kind, (limit, window_s) in _WINDOWS.items():
        times = [t for t, kinds in sends if kind in kinds]
        for start in times:
            # The tolerance keeps float sums such as 0.1 + 0.2 from counting a boundary send twice.
            inside = [t for t in times if start <= t < start + window_s - 1e-9]
            assert len(inside) <= limit, (kind, start, inside)


def test_no_window_ever_exceeds_its_limit() -> None:
    requests = [("GET", "/api/v1/markets")] * 40
    for i, position in enumerate((3, 11, 25)):
        requests.insert(position + i, ("POST", "/api/v1/session"))
    for i, position in enumerate((1, 2, 9, 30, 31)):
        requests.insert(position + i, ("POST", "/api/v1/positions"))
    sends = _send_all(requests)
    assert len(sends) == 48
    _assert_no_window_exceeded(sends)


def test_general_window_counts_the_delayed_login_at_its_send_time() -> None:
    login = ("POST", "/api/v1/session")
    sends = _send_all([login, login] + [("GET", "/api/v1/markets")] * 10)
    assert sends[1][0] == pytest.approx(1.0)
    general = [t for t, _ in sends if 1.0 <= t < 2.0 - 1e-9]
    assert len(general) <= 10
    _assert_no_window_exceeded(sends)


def test_second_trade_waits_a_tenth() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock)
    limiter.acquire("POST", "/api/v1/positions")
    limiter.acquire("POST", "/api/v1/positions")
    assert clock.sleeps == [pytest.approx(0.1)]


def test_second_session_waits_a_second() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock)
    limiter.acquire("POST", "/api/v1/session")
    limiter.acquire("POST", "/api/v1/session")
    assert clock.sleeps == [pytest.approx(1.0)]


def test_concurrent_acquires_never_share_a_slot() -> None:
    clock = FrozenClock()
    limiter = RateLimiter(clock)
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        limiter.acquire("POST", "/api/v1/session")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # One free slot; the other three each get their own later slot.
    assert sorted(clock.sleeps) == [pytest.approx(1.0), pytest.approx(2.0), pytest.approx(3.0)]
