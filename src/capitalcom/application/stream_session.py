"""The stream as the caller sees it: one subscription set kept across reconnects.

A dropped link is replaced with backoff, the whole set is resubscribed, and the interruption
is queued as a ``Gap`` behind the events that arrived before it, so nothing is lost silently.
"""

import random
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any, TypeAlias

from capitalcom.application.ports import Clock, StreamTransport
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import RetryPolicy, backoff_delay
from capitalcom.application.session import SessionManager
from capitalcom.application.stream_frames import (
    OHLC_SUBSCRIBE,
    OHLC_UNSUBSCRIBE,
    QUOTES_SUBSCRIBE,
    QUOTES_UNSUBSCRIBE,
)
from capitalcom.application.stream_link import AckTimeoutError, StreamLink
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
from capitalcom.domain.subscriptions import OhlcKey, Subscriptions

MAX_RECONNECTS = 5
# 1, 2, 4, 8, then 16 s, each with equal jitter (addendum 5.3).
RECONNECT_POLICY = RetryPolicy(max_attempts=MAX_RECONNECTS, base_delay_s=1.0, max_delay_s=16.0)
_ORDER = {resolution: index for index, resolution in enumerate(Resolution)}

StreamEvent: TypeAlias = Quote | Candle | Gap
# A change is (destination, payload, keys the ack must cover, whether the keys were added).
_Change: TypeAlias = tuple[str, dict[str, Any], list[str], bool]


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
        return self._change(lambda: self._subscribe_quotes(epics))

    def unsubscribe_quotes(self, epics: Sequence[str]) -> Result[None, CapitalComError]:
        """Stop quotes of subscribed epics."""
        return self._change(lambda: self._unsubscribe_quotes(epics))

    def subscribe_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str],
        candle_type: CandleType | str,
    ) -> Result[None, CapitalComError]:
        """Subscribe bars of each epic in each resolution, for the keys not subscribed yet."""
        return self._change(lambda: self._subscribe_ohlc(epics, resolutions, candle_type))

    def unsubscribe_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str] | None,
        candle_types: Sequence[CandleType | str] | None,
    ) -> Result[None, CapitalComError]:
        """Stop bars of the epics; ``None`` means every resolution or candle type."""
        return self._change(lambda: self._unsubscribe_ohlc(epics, resolutions, candle_types))

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

    def _change(self, plan: Callable[[], _Change | None]) -> Result[None, CapitalComError]:
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

    def _subscribe_quotes(self, epics: Sequence[str]) -> _Change | None:
        new = list(self._subs.add_quotes(epics))
        return (QUOTES_SUBSCRIBE, {"epics": new}, new, True) if new else None

    def _unsubscribe_quotes(self, epics: Sequence[str]) -> _Change:
        gone = list(self._subs.remove_quotes(epics))
        return (QUOTES_UNSUBSCRIBE, {"epics": gone}, gone, False)

    def _subscribe_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str],
        candle_type: CandleType | str,
    ) -> _Change | None:
        new = self._subs.add_ohlc(epics, resolutions, candle_type)
        if not new:
            return None
        # Every key this payload implies is in the set: the epics and resolutions come from
        # the new keys, which are a subset of the caller's epics x resolutions.
        payload = {
            "epics": list(dict.fromkeys(k.epic for k in new)),
            "resolutions": [r.value for r in dict.fromkeys(k.resolution for k in new)],
            "type": new[0].candle_type.value,
        }
        return (OHLC_SUBSCRIBE, payload, [k.wire() for k in new], True)

    def _unsubscribe_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str] | None,
        candle_types: Sequence[CandleType | str] | None,
    ) -> _Change:
        gone = self._subs.remove_ohlc(epics, resolutions, candle_types)
        payload: dict[str, Any] = {"epics": list(dict.fromkeys(k.epic for k in gone))}
        if resolutions is not None:
            payload["resolutions"] = [Resolution(r).value for r in resolutions]
        if candle_types is not None:
            payload["types"] = [CandleType(t).value for t in candle_types]
        return (OHLC_UNSUBSCRIBE, payload, [k.wire() for k in gone], False)

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
        quotes = list(self._subs.quotes)
        requests: list[tuple[str, dict[str, Any], list[str]]] = []
        if quotes:
            requests.append((QUOTES_SUBSCRIBE, {"epics": quotes}, quotes))
        # One frame per exact resolution set and candle type: a frame for epics x resolutions
        # would also subscribe pairs the caller has removed.
        groups: dict[tuple[tuple[Resolution, ...], CandleType], list[str]] = {}
        for (epic, candle), resolutions in self._ohlc_by_epic().items():
            groups.setdefault((resolutions, candle), []).append(epic)
        for (resolutions, candle), epics in groups.items():
            payload = {
                "epics": epics,
                "resolutions": [r.value for r in resolutions],
                "type": candle.value,
            }
            keys = [OhlcKey(e, r, candle).wire() for e in epics for r in resolutions]
            requests.append((OHLC_SUBSCRIBE, payload, keys))
        for destination, payload, keys in requests:
            sent = link.request(destination, payload, keys)
            if isinstance(sent, Err):
                return Err(sent.error)
        return Ok(None)

    def _ohlc_by_epic(self) -> dict[tuple[str, CandleType], tuple[Resolution, ...]]:
        found: dict[tuple[str, CandleType], list[Resolution]] = {}
        for key in self._subs.ohlc:
            found.setdefault((key.epic, key.candle_type), []).append(key.resolution)
        return {k: tuple(sorted(v, key=_ORDER.__getitem__)) for k, v in found.items()}

    def _fail(self, error: CapitalComError) -> Err[CapitalComError]:
        if isinstance(error, AuthenticationError):
            self.close()
        return Err(error)


def _reason(error: TransportError) -> GapReason:
    if isinstance(error, AckTimeoutError) or not error.reached_server:
        return GapReason.NETWORK
    return GapReason.SERVER_CLOSED
