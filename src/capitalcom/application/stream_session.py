"""The stream as the caller sees it: one subscription set kept across reconnects.

A dropped link is replaced with backoff, the whole set is resubscribed, and the interruption
is queued as a ``Gap`` behind the events that arrived before it, so nothing is lost silently.
"""

import random
import threading
from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TypeAlias, TypeVar

from capitalcom.application import stream_requests as requests
from capitalcom.application.ports import Clock, StreamTransport
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.session import SessionManager
from capitalcom.application.stream_gaps import gap_reason, read_at
from capitalcom.application.stream_link import StreamLink
from capitalcom.application.stream_reconnect import open_resubscribed
from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import (
    AuthenticationError,
    CapitalComError,
    ResponseFormatError,
    SubscriptionError,
    TransportError,
    ValidationError,
)
from capitalcom.domain.streaming import Candle, CandleType, Gap, GapReason, Quote
from capitalcom.domain.subscriptions import Subscriptions

StreamEvent: TypeAlias = Quote | Candle | Gap
T = TypeVar("T")


class StreamClosedError(ValidationError):
    """The stream was closed, possibly from another thread; iteration ends on it."""

    def __init__(self) -> None:
        super().__init__("stream is closed")


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
        # Errors wait in line too: an undecodable frame at its position among the events
        # (see StreamLink), and the error a stream gave up with behind what it had read.
        self._ready: deque[StreamEvent | CapitalComError] = deque()
        self._last_event_at = clock.now_utc()
        self._account: str | None = None
        self._closed = False
        self._busy = threading.Lock()

    @property
    def closed(self) -> bool:
        """True once the socket is closed for good: by ``close()``, or because it gave up."""
        return self._closed

    @property
    def exhausted(self) -> bool:
        """True once closed with nothing left to deliver; iteration ends here."""
        return self._closed and not self._ready

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
        return self._exclusive(self._next_event)

    def _next_event(self) -> Result[StreamEvent, CapitalComError]:
        while True:
            if self._ready:
                item = self._ready.popleft()
                return Err(item) if isinstance(item, CapitalComError) else Ok(item)
            if self._closed or self._link is None:
                # Also a stream whose open() failed: nothing will ever arrive on it.
                return Err(StreamClosedError())
            link = self._usable()
            if isinstance(link, Err):
                self._queue(link.error)
                continue  # what a failed account-switch reconnect read comes out first
            if self._ready:
                continue  # an account-switch reconnect has just queued its Gap
            incoming = link.value.next_incoming()
            if isinstance(incoming, Err):
                error = incoming.error
                if self._closed:
                    # Closed from another thread: the failed read is the close, not a drop.
                    return Err(StreamClosedError())
                if not isinstance(error, TransportError):
                    self._queue(self._fail(error).error)
                    continue
                reconnected = self._reconnect(gap_reason(error))
                if isinstance(reconnected, Err):
                    self._queue(reconnected.error)
            elif incoming.value is not None:
                event = incoming.value.value
                self._last_event_at = max(
                    self._last_event_at, read_at(event, self._clock.now_utc())
                )
                return Ok(event)

    def close(self) -> None:
        """Close the socket and drop what was not read: the caller asked to stop."""
        self._closed = True
        self._ready.clear()
        if self._link is not None:
            self._link.close()
            self._link = None

    def _give_up(self) -> None:
        # Unlike close(), keeps what was read: the caller did not ask to drop it, and a
        # trader reading prices must see every one that arrived before the stream ended.
        self._closed = True
        self._drop_link()

    def _queue(self, error: CapitalComError) -> None:
        # Inside next_event an error waits behind what was read before it. A close from
        # another thread emptied the queue and needs no place in it.
        if not isinstance(error, StreamClosedError):
            self._ready.append(error)

    def _exclusive(
        self, call: Callable[[], Result[T, CapitalComError]]
    ) -> Result[T, CapitalComError]:
        # One socket cannot be read by two threads, and an ack read by the other thread
        # would be lost; a second caller is refused instead of corrupting the stream.
        if not self._busy.acquire(blocking=False):
            return Err(
                ValidationError("use a stream from one thread; only close() may come from another")
            )
        try:
            return call()
        finally:
            self._busy.release()

    def _change(self, plan: Callable[[], requests.Change | None]) -> Result[None, CapitalComError]:
        return self._exclusive(lambda: self._apply(plan))

    def _apply(self, plan: Callable[[], requests.Change | None]) -> Result[None, CapitalComError]:
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
            return self._reconnect(gap_reason(failure))
        if added:
            # Never acknowledged: kept, they would make a retry a silent no-op.
            self._subs.discard(keys)
        return self._fail(failure)

    def _usable(self) -> Result[StreamLink, CapitalComError]:
        if self._closed or self._link is None:
            return Err(StreamClosedError())
        # None means the session is between logins, not that it moved to another account.
        account = self._session.current_account_id
        if account is not None and account != self._account:
            reconnected = self._reconnect(GapReason.ACCOUNT_SWITCHED)
            if isinstance(reconnected, Err):
                return reconnected
        assert self._link is not None  # noqa: S101 - a successful reconnect sets the link
        return Ok(self._link)

    def _drop_link(self) -> datetime:
        """Close the link, keeping what it buffered; return when the last kept event was read."""
        since = self._last_event_at
        if self._link is not None:
            # Events read before the drop come out before the Gap that follows them, and the
            # gap starts after the last of them.
            drained = [
                item if isinstance(item, ResponseFormatError) else item.value
                for item in self._link.drain()
            ]
            read = [item for item in drained if not isinstance(item, ResponseFormatError)]
            since = max([since, *(read_at(event, self._clock.now_utc()) for event in read)])
            self._ready.extend(drained)
            self._link.close()
            self._link = None
        return since

    def _reconnect(self, reason: GapReason) -> Result[None, CapitalComError]:
        since = self._drop_link()
        opened = open_resubscribed(
            self._transport,
            self._url,
            self._session,
            self._clock,
            self._subs,
            self._rand,
            lambda: self._closed,
        )
        if isinstance(opened, Err):
            self._give_up()
            return Err(opened.error)
        link = opened.value
        if link is None:
            return Err(StreamClosedError())
        self._link = link
        # Checked after the link is stored: a close() in between either sees the link and
        # closes it, or is seen here.
        if self._closed:
            link.close()
            self._link = None
            return Err(StreamClosedError())
        self._account = self._session.current_account_id or self._account
        until = max(self._clock.now_utc(), since)
        self._ready.append(Gap(since, until, reason))
        # The next gap starts after this one, not again from before it.
        self._last_event_at = until
        return Ok(None)

    def _fail(self, error: CapitalComError) -> Err[CapitalComError]:
        if isinstance(error, AuthenticationError):
            self._give_up()
        return Err(error)
