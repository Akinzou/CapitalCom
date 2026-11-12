"""Replacing a dropped stream link: backoff, connect, then resubscribe the whole set."""

from collections.abc import Callable

from capitalcom.application.ports import Clock, StreamTransport
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import RetryPolicy, backoff_delay
from capitalcom.application.session import SessionManager
from capitalcom.application.stream_link import StreamLink
from capitalcom.application.stream_requests import resubscribe_requests
from capitalcom.domain.errors import CapitalComError, StreamError, TransportError
from capitalcom.domain.subscriptions import Subscriptions

MAX_RECONNECTS = 5
# 1, 2, 4, 8, then 16 s, each with equal jitter (addendum 5.3).
RECONNECT_POLICY = RetryPolicy(max_attempts=MAX_RECONNECTS, base_delay_s=1.0, max_delay_s=16.0)


def open_resubscribed(
    transport: StreamTransport,
    url: str,
    session: SessionManager,
    clock: Clock,
    subs: Subscriptions,
    rand: Callable[[], float],
    closed: Callable[[], bool],
) -> Result[StreamLink | None, CapitalComError]:
    """A new link carrying every subscription in ``subs``, or ``None`` if closed meanwhile.

    ``closed`` is re-checked around the slow steps: a close from another thread must not be
    answered with a fresh subscription. A link returned while a close lands is the caller's
    to close.
    """
    last: CapitalComError | None = None
    for attempt in range(MAX_RECONNECTS):
        clock.sleep(backoff_delay(RECONNECT_POLICY, attempt, None, rand))
        if closed():
            return Ok(None)
        connected = transport.connect(url)
        if isinstance(connected, Err):
            last = connected.error
            continue
        link = StreamLink(connected.value, session, clock)
        resubscribed = _resubscribe(link, subs) if not closed() else Ok(None)
        if isinstance(resubscribed, Ok):
            return Ok(link)
        link.close()
        last = resubscribed.error
        if not isinstance(last, TransportError):
            # A refused login or a refused key will not change on the next attempt.
            return Err(last)
    error = StreamError(f"stream lost; {MAX_RECONNECTS} reconnects failed")
    error.__cause__ = last
    return Err(error)


def _resubscribe(link: StreamLink, subs: Subscriptions) -> Result[None, CapitalComError]:
    for destination, payload, keys in resubscribe_requests(subs):
        sent = link.request(destination, payload, keys)
        if isinstance(sent, Err):
            return Err(sent.error)
    return Ok(None)
