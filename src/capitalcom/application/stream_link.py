"""One open stream connection: acknowledged requests, buffered events and the keepalive.

The link never reconnects; it reports every failure as an ``Err`` and leaves the decision to
the stream session above it.
"""

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from capitalcom.application.logs import get_logger
from capitalcom.application.ports import Clock, StreamConnection
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.session import SessionManager, SessionTokens
from capitalcom.application.stream_frames import (
    INVALID_SESSION,
    PING,
    Ack,
    Event,
    check_ack,
    decode_frame,
    encode_frame,
    is_invalid_session,
)
from capitalcom.domain.errors import (
    AuthenticationError,
    CapitalComError,
    ResponseFormatError,
    TransportError,
)

# Half the server's 10-minute session: one late ping still lands inside it.
KEEPALIVE_S = 300.0
ACK_TIMEOUT_S = 10.0
# How long an overdue keepalive answer may still take once the queue is empty: a socket that
# stopped reading while its queue was full refills only after the queue was read from.
DRAIN_GRACE_S = 1.0

_log = get_logger("capitalcom.stream")


class AckTimeoutError(TransportError):
    """No acknowledgement arrived in time: the link is presumed dead, not closed by the server.

    Its own type, because ``reached_server`` alone cannot tell it from a close frame: both
    reached the server, but only a close frame means the server ended the stream.
    """


@dataclass(frozen=True, slots=True)
class _PendingPing:
    correlation_id: str
    sent_at: float
    tokens: SessionTokens
    retried: bool


class StreamLink:
    """Requests on one connection, matched to their acks by correlation id."""

    def __init__(self, connection: StreamConnection, session: SessionManager, clock: Clock) -> None:
        self._connection = connection
        self._session = session
        self._clock = clock
        self._buffer: deque[Event] = deque()
        self._last_id = 0
        self._last_ping = clock.monotonic()
        self._ping: _PendingPing | None = None

    def request(
        self, destination: str, payload: Mapping[str, Any], expected_keys: Sequence[str]
    ) -> Result[Ack, CapitalComError]:
        """Send one request and wait for its ack; events that arrive meanwhile are kept."""
        for retried in (False, True):
            sent = self._send(destination, payload)
            if isinstance(sent, Err):
                return sent
            correlation_id, tokens = sent.value
            ack = self._await(correlation_id)
            if isinstance(ack, Err):
                return ack
            if not is_invalid_session(ack.value):
                checked = check_ack(ack.value, expected_keys)
                return Err(checked.error) if isinstance(checked, Err) else ack
            # The server refused the tokens the frame carried (P7: after a logout or expiry);
            # one resend with fresh ones tells a stale copy from a refused login.
            self._session.invalidate(tokens)
            if retried:
                break
        return Err(AuthenticationError(401, INVALID_SESSION, ""))

    def next_incoming(self) -> Result[Event | None, CapitalComError]:
        """Return the next event, or ``None`` when a receive ended without one.

        A due keepalive is sent before receiving, so a caller that was busy for longer than
        the interval does not wait for another frame before the session is renewed.
        """
        if self._buffer:
            return Ok(self._buffer.popleft())
        timeout = self._keepalive()
        if isinstance(timeout, Err):
            return timeout
        if not self._buffer:
            received = self._connection.receive(timeout.value)
            if isinstance(received, Err):
                return Err(received.error)
            if received.value is not None:
                routed = self._route(received.value, None)
                if isinstance(routed, Err):
                    return routed
        return Ok(self._buffer.popleft() if self._buffer else None)

    def drain(self) -> list[Event]:
        """Hand over the events buffered so far, so they outlive a link that failed."""
        events = list(self._buffer)
        self._buffer.clear()
        return events

    def close(self) -> None:
        """Close the connection."""
        self._connection.close()

    def _keepalive(self) -> Result[float, CapitalComError]:
        # An overdue ack may be sitting behind frames a slow caller has not read yet, so the
        # queue is drained before the link is declared dead.
        while (ping := self._ping) is not None and self._overdue(ping):
            received = self._connection.receive(DRAIN_GRACE_S)
            if isinstance(received, Err):
                return Err(received.error)
            if received.value is None:
                return Err(AckTimeoutError("no keepalive acknowledgement"))
            routed = self._route(received.value, None)
            if isinstance(routed, Err):
                return routed
        now = self._clock.monotonic()
        if self._ping is not None:
            return Ok(self._ping.sent_at + ACK_TIMEOUT_S - now)
        due = self._last_ping + KEEPALIVE_S
        if now < due:
            return Ok(due - now)
        sent = self._send_ping(retried=False)
        return sent if isinstance(sent, Err) else Ok(ACK_TIMEOUT_S)

    def _overdue(self, ping: _PendingPing) -> bool:
        return self._clock.monotonic() >= ping.sent_at + ACK_TIMEOUT_S

    def _send_ping(self, *, retried: bool) -> Result[None, CapitalComError]:
        sent = self._send(PING, None)
        if isinstance(sent, Err):
            return sent
        correlation_id, tokens = sent.value
        self._ping = _PendingPing(correlation_id, self._clock.monotonic(), tokens, retried)
        return Ok(None)

    def _ping_answered(self, ack: Ack) -> Result[None, CapitalComError]:
        ping = self._ping
        if ping is None or ack.correlation_id != ping.correlation_id:
            _log.debug("ignored an acknowledgement nobody waits for")
            return Ok(None)
        self._ping = None
        if is_invalid_session(ack):
            self._session.invalidate(ping.tokens)
            if ping.retried:
                return Err(AuthenticationError(401, INVALID_SESSION, ""))
            return self._send_ping(retried=True)
        # P1: a ping on the stream keeps the REST session alive as well.
        self._session.mark_used()
        self._last_ping = self._clock.monotonic()
        return Ok(None)

    def _send(
        self, destination: str, payload: Mapping[str, Any] | None
    ) -> Result[tuple[str, SessionTokens], CapitalComError]:
        tokens = self._session.tokens()
        if isinstance(tokens, Err):
            return tokens
        self._last_id += 1
        correlation_id = str(self._last_id)
        frame = encode_frame(destination, correlation_id, tokens.value, payload)
        sent = self._connection.send(frame)
        return Err(sent.error) if isinstance(sent, Err) else Ok((correlation_id, tokens.value))

    def _await(self, correlation_id: str) -> Result[Ack, CapitalComError]:
        deadline = self._clock.monotonic() + ACK_TIMEOUT_S
        while (left := deadline - self._clock.monotonic()) > 0:
            received = self._connection.receive(left)
            if isinstance(received, Err):
                return Err(received.error)
            if received.value is None:
                continue
            routed = self._route(received.value, correlation_id)
            if isinstance(routed, Err):
                return routed
            if routed.value is not None:
                return Ok(routed.value)
        return Err(AckTimeoutError("no acknowledgement"))

    def _route(self, text: str, awaited: str | None) -> Result[Ack | None, CapitalComError]:
        """Buffer an event, settle a ping ack, or return the ack ``awaited`` is waiting for."""
        try:
            frame = decode_frame(text)
        except ResponseFormatError as error:
            return Err(error)
        if isinstance(frame, Event):
            self._buffer.append(frame)
        elif isinstance(frame, Ack):
            if frame.correlation_id == awaited:
                return Ok(frame)
            handled = self._ping_answered(frame)
            if isinstance(handled, Err):
                return handled
        else:
            _log.debug("skipped a stream frame of unknown kind %r", frame.destination)
        return Ok(None)
