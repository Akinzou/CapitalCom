"""The stream as the caller sees it: one subscription set kept across reconnects.

A dropped link is replaced with backoff, the whole set is resubscribed, and the interruption
is queued as a ``Gap`` behind the events that arrived before it, so nothing is lost silently.
"""

import random
from collections import deque
from collections.abc import Callable, Sequence
from typing import TypeAlias

from capitalcom.application import stream_requests as requests
from capitalcom.application.ports import Clock, StreamTransport
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import RetryPolicy, backoff_delay
from capitalcom.application.session import SessionManager
from capitalcom.application.stream_link import AckTimeoutError, StreamLink
from capitalcom.application.stream_requests import resubscribe_requests
from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import (
    AuthenticationError,
    CapitalComError,
    StreamError,
    SubscriptionError,
    TransportError,
    ValidationError,
)
from capitalcom.domain.streaming import Candle, CandleType, Gap, GapReason, Quote
from capitalcom.domain.subscriptions import Subscriptions

MAX_RECONNECTS = 5
# 1, 2, 4, 8, then 16 s, each with equal jitter (addendum 5.3).
RECONNECT_POLICY = RetryPolicy(max_attempts=MAX_RECONNECTS, base_delay_s=1.0, max_delay_s=16.0)

StreamEvent: TypeAlias = Quote | Candle | Gap


class StreamSession:
    """Subscriptions, events and reconnects of one stream; never raises."""

    def __init__(
        self,
        transport: StreamTransport,
        session: SessionManager,
        clock: Clock,
        url: str,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self._transport = transport
        self._session = session
        self._clock = clock
        self._url = url
        self._rand = rand
        self._subs = Subscriptions()
        self._link: StreamLink | None = None
        self._ready: deque[StreamEvent] = deque()
        self._last_event_at = clock.now_utc()
        self._account: str | None = None
        self._closed = False

    @property
    def closed(self) -> bool:
        """True after ``close()``, or once the stream gave up or was refused for good."""
        return self._closed

    @property
    def subscriptions(self) -> Subscriptions:
        """What the stream is subscribed to; it matches what the server accepted."""
        return self._subs

    def open(self) -> Result[None, CapitalComError]:
        """Log in if needed and open the connection; a failure here is not retried."""
        if self._closed or self._link is not None:
            return Err(ValidationError("a stream can be opened once"))
        tokens = self._session.tokens()
        if isinstance(tokens, Err):
            return tokens
        self._account = self._session.current_account_id
        connected = self._transport.connect(self._url)
        if isinstance(connected, Err):
            return Err(connected.error)
        self._link = StreamLink(connected.value, self._session, self._clock)
        self._last_event_at = self._clock.now_utc()
        return Ok(None)

    def subscribe_quotes(self, epics: Sequence[str]) -> Result[None, CapitalComError]:
        """Subscribe quotes of the epics not subscribed yet."""
        return self._change(lambda: requests.subscribe_quotes(self._subs, epics))

    def unsubscribe_quotes(self, epics: Sequence[str]) -> Result[None, CapitalComError]:
        """Stop quotes of subscribed epics."""
        return self._change(lambda: requests.unsubscribe_quotes(self._subs, epics))

    def subscribe_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str],
        candle_type: CandleType | str,
    ) -> Result[None, CapitalComError]:
        """Subscribe bars of each epic in each resolution, for the keys not subscribed yet."""
        return self._change(
            lambda: requests.subscribe_ohlc(self._subs, epics, resolutions, candle_type)
        )

    def unsubscribe_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str] | None,
        candle_types: Sequence[CandleType | str] | None,
    ) -> Result[None, CapitalComError]:
        """Stop bars of the epics; ``None`` means every resolution or candle type."""
        return self._change(
            lambda: requests.unsubscribe_ohlc(self._subs, epics, resolutions, candle_types)
        )

    def next_event(self) -> Result[StreamEvent, CapitalComError]:
        """Block until the next quote, bar or gap; reconnects happen in here."""
        while True:
            if self._ready:
                return Ok(self._ready.popleft())
            link = self._usable()
            if isinstance(link, Err):
                return link
            if self._ready:
                continue  # an account-switch reconnect has just queued its Gap
            incoming = link.value.next_incoming()
            if isinstance(incoming, Err):
                error = incoming.error
                if not isinstance(error, TransportError):
                    return self._fail(error)
                reconnected = self._reconnect(_reason(error))
                if isinstance(reconnected, Err):
                    return reconnected
            elif incoming.value is not None:
                self._last_event_at = self._clock.now_utc()
                return Ok(incoming.value.value)

    def close(self) -> None:
        """Close the socket; the server drops its subscriptions with it."""
        self._closed = True
        self._ready.clear()
        if self._link is not None:
            self._link.close()
            self._link = None

    def _change(self, plan: Callable[[], requests.Change | None]) -> Result[None, CapitalComError]:
        link = self._usable()
        if isinstance(link, Err):
            return link
        try:
            change = plan()
        except ValidationError as error:
            return Err(error)
        if change is None:
            return Ok(None)
        destination, payload, keys, added = change
        sent = link.value.request(destination, payload, keys)
        if isinstance(sent, Ok):
            return Ok(None)
        failure = sent.error
        if isinstance(failure, SubscriptionError):
            if added:
                # Only the requested keys: an OHLC refusal may name the bare epic, which is
                # also the key of that epic's quotes.
                self._subs.discard([key for key in keys if key in failure.refused])
            return Err(failure)
        if isinstance(failure, TransportError):
            # The keys stay in the set, so the reconnect resubscribes them with the rest.
            return self._reconnect(_reason(failure))
        return self._fail(failure)

    def _usable(self) -> Result[StreamLink, CapitalComError]:
        if self._closed or self._link is None:
            return Err(ValidationError("stream is closed"))
        # None means the session is between logins, not that it moved to another account.
        account = self._session.current_account_id
        if account is not None and account != self._account:
            reconnected = self._reconnect(GapReason.ACCOUNT_SWITCHED)
            if isinstance(reconnected, Err):
                return reconnected
        assert self._link is not None  # noqa: S101 - a successful reconnect sets the link
        return Ok(self._link)

    def _reconnect(self, reason: GapReason) -> Result[None, CapitalComError]:
        since = self._last_event_at
        if self._link is not None:
            # Events read before the drop come out before the Gap that follows them.
            self._ready.extend(event.value for event in self._link.drain())
            self._link.close()
            self._link = None
        last: CapitalComError | None = None
        for attempt in range(MAX_RECONNECTS):
            self._clock.sleep(backoff_delay(RECONNECT_POLICY, attempt, None, self._rand))
            connected = self._transport.connect(self._url)
            if isinstance(connected, Err):
                last = connected.error
                continue
            link = StreamLink(connected.value, self._session, self._clock)
            resubscribed = self._resubscribe(link)
            if isinstance(resubscribed, Ok):
                self._link = link
                self._account = self._session.current_account_id or self._account
                self._ready.append(Gap(since, self._clock.now_utc(), reason))
                return Ok(None)
            link.close()
            last = resubscribed.error
            if not isinstance(last, TransportError):
                # A refused login or a refused key will not change on the next attempt.
                self.close()
                return Err(last)
        self.close()
        error = StreamError(f"stream lost; {MAX_RECONNECTS} reconnects failed")
        error.__cause__ = last
        return Err(error)

    def _resubscribe(self, link: StreamLink) -> Result[None, CapitalComError]:
        for destination, payload, keys in resubscribe_requests(self._subs):
            sent = link.request(destination, payload, keys)
            if isinstance(sent, Err):
                return Err(sent.error)
        return Ok(None)

    def _fail(self, error: CapitalComError) -> Err[CapitalComError]:
        if isinstance(error, AuthenticationError):
            self.close()
        return Err(error)


def _reason(error: TransportError) -> GapReason:
    if isinstance(error, AckTimeoutError) or not error.reached_server:
        return GapReason.NETWORK
    return GapReason.SERVER_CLOSED
