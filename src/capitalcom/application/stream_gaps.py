"""How a ``Gap`` is dated and why it happened: pure rules shared by the stream session."""

from datetime import datetime

from capitalcom.application.stream_link import AckTimeoutError
from capitalcom.domain.errors import TransportError
from capitalcom.domain.streaming import Candle, GapReason, Quote


def read_at(event: Quote | Candle, now: datetime) -> datetime:
    """When ``event`` counts as read, for dating the gap that may follow it.

    A quote's server time, bounded by now: a reader that lags behind the feed would otherwise
    date the gap from when it read the last quote, and the quotes lost in between would fall
    outside it. A bar's time is its start, which for an hourly bar is up to an hour old, so a
    bar counts from when it was read.
    """
    return now if isinstance(event, Candle) else min(now, event.time)


def gap_reason(error: TransportError) -> GapReason:
    """Why a link that failed with ``error`` left a gap."""
    if isinstance(error, AckTimeoutError) or not error.reached_server:
        return GapReason.NETWORK
    return GapReason.SERVER_CLOSED
