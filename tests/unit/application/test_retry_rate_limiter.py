import threading
from datetime import timedelta
from email.utils import format_datetime

import pytest

from capitalcom.application.rate_limiter import (
    RateLimiter,
    RequestKind,
    TokenBucket,
    classify,
)
from capitalcom.application.retry import (
    RetryPolicy,
    backoff_delay,
    is_idempotent,
    parse_retry_after,
)
from tests.fakes import EPOCH, FakeClock


def test_retry_after_delta_seconds() -> None:
    assert parse_retry_after("2", EPOCH) == 2.0


def test_retry_after_http_date_in_future() -> None:
    value = format_datetime(EPOCH + timedelta(seconds=3), usegmt=True)
    assert parse_retry_after(value, EPOCH) == pytest.approx(3.0)


def test_retry_after_http_date_in_past_is_zero() -> None:
    value = format_datetime(EPOCH - timedelta(seconds=30), usegmt=True)
    assert parse_retry_after(value, EPOCH) == 0.0


@pytest.mark.parametrize("value", ["soon", None, "", "-5", "nan", "inf"])
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


def test_only_get_is_idempotent() -> None:
    assert is_idempotent("GET")
    assert not any(is_idempotent(m) for m in ("POST", "PUT", "DELETE"))


def test_classify() -> None:
    assert classify("POST", "/api/v1/session") == {RequestKind.GENERAL, RequestKind.SESSION}
    assert classify("POST", "/api/v1/positions") == {RequestKind.GENERAL, RequestKind.TRADE}
    assert classify("POST", "/api/v1/workingorders") == {RequestKind.GENERAL, RequestKind.TRADE}
    assert classify("GET", "/api/v1/positions") == {RequestKind.GENERAL}
    assert classify("PUT", "/api/v1/session") == {RequestKind.GENERAL}


def test_token_bucket_reserves_future_slots() -> None:
    bucket = TokenBucket(rate_per_s=1.0, capacity=1)
    assert bucket.reserve(0.0) == 0.0
    assert bucket.reserve(0.0) == pytest.approx(1.0)
    assert bucket.reserve(0.0) == pytest.approx(2.0)


def test_eleven_general_requests_sleep_once_for_a_tenth() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock)
    for _ in range(11):
        limiter.acquire("GET", "/api/v1/accounts")
    assert clock.sleeps == [pytest.approx(0.1)]


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


class FrozenClock(FakeClock):
    """Records sleeps without moving time, so every thread reserves at t=0."""

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


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
