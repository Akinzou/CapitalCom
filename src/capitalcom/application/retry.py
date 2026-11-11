"""When a request may be repeated, and how long to wait before repeating it."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from capitalcom.application.logs import get_logger

_log = get_logger(__name__)

# A server asking for more than a minute is better surfaced as RateLimitError than obeyed by a
# trading bot that silently freezes.
MAX_RETRY_AFTER_S = 60.0


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many attempts a retryable request gets, and the backoff between them."""

    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0


def backoff_delay(
    policy: RetryPolicy, attempt: int, retry_after: float | None, rand: Callable[[], float]
) -> float:
    """Seconds to wait before retry number ``attempt`` (0-based).

    ``Retry-After`` wins when the server sent it. Otherwise exponential backoff with equal
    jitter: half the delay is fixed so retries never bunch at zero, half is random so many
    clients do not retry in lockstep.
    """
    if retry_after is not None:
        return min(retry_after, MAX_RETRY_AFTER_S)
    delay = min(policy.max_delay_s, policy.base_delay_s * 2.0**attempt)
    return delay * (0.5 + rand() / 2)


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    """Read ``Retry-After`` as delta-seconds or an HTTP-date; ``None`` when absent or invalid."""
    if not value:
        return None
    text = value.strip()
    if text.isdigit():
        return float(text)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        _log.debug("ignoring unparseable Retry-After header %r", value)
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    seconds = (when - now).total_seconds()
    return max(0.0, seconds) if math.isfinite(seconds) else None


def is_idempotent(method: str) -> bool:
    """True when repeating the request cannot change state on the server.

    Only GET: Capital.com's DELETE closes a position and PUT amends one, and a repeated close
    after a lost response can hit a position reopened in the meantime.
    """
    return method.upper() == "GET"
