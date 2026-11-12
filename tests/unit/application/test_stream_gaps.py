"""Gaps and closing: what ``since`` reports, and a close from another thread."""

import json
from datetime import timedelta
from typing import Any

from capitalcom.application.ports import StreamConnection
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.stream_frames import INVALID_SESSION
from capitalcom.application.stream_session import StreamClosedError, StreamSession
from capitalcom.domain.errors import AuthenticationError, TransportError, ValidationError
from capitalcom.domain.streaming import Gap, Quote
from tests.fakes import (
    EPOCH,
    FakeClock,
    FakeConnection,
    FakeStreamTransport,
    ack_frame,
    auto_ack,
    quote_frame,
)
from tests.unit.application.stream_support import URL, make_session, next_value, open_stream

RESET = TransportError("reset", reached_server=False)

EPOCH_MS = int(EPOCH.timestamp() * 1000)


def test_gap_since_is_the_last_event_time_for_a_lagging_reader() -> None:
    late = quote_frame("A", timestamp=EPOCH_MS + 3000)
    first = FakeConnection([ack_frame("1", {"GOLD": "PROCESSED"}), late, RESET])
    stream, _, clock, _ = open_stream([first, FakeConnection([], auto_ack)])
    stream.subscribe_quotes(["GOLD"])
    clock.advance(20)
    assert isinstance(next_value(stream), Quote)
    gap = next_value(stream)
    assert isinstance(gap, Gap)
    assert gap.since == EPOCH + timedelta(seconds=3)
    assert gap.until >= gap.since


def test_gap_since_counts_events_read_before_the_drop() -> None:
    buffered = quote_frame("C", timestamp=EPOCH_MS + 5000)
    first = FakeConnection([ack_frame("1", {"GOLD": "PROCESSED"}), buffered])
    stream, _, clock, _ = open_stream([first, FakeConnection([], auto_ack)])
    stream.subscribe_quotes(["GOLD"])
    clock.advance(6)
    stream.subscribe_quotes(["OIL"])
    assert isinstance(next_value(stream), Quote)
    gap = next_value(stream)
    assert isinstance(gap, Gap)
    assert gap.since == EPOCH + timedelta(seconds=5)


def test_close_during_a_read_ends_without_reconnecting() -> None:
    class ClosedMidRead(FakeConnection):
        def receive(self, timeout_s: float) -> "Result[str | None, TransportError]":
            stream.close()  # what another thread calling close() looks like to the reader
            return Err(TransportError("closed by this client", reached_server=True))

    stream, transport, clock, _ = open_stream([ClosedMidRead(), FakeConnection([], auto_ack)])
    result = stream.next_event()
    assert isinstance(result, Err)
    assert isinstance(result.error, StreamClosedError)
    assert transport.urls == [URL]
    assert clock.sleeps == []


def test_close_during_a_reconnect_closes_the_new_connection() -> None:
    second = FakeConnection([], auto_ack)

    class ClosingTransport(FakeStreamTransport):
        def connect(self, url: str) -> "Result[StreamConnection, TransportError]":
            if self.urls:
                stream.close()
            return super().connect(url)

    clock = FakeClock()
    session, _ = make_session(clock)
    transport = ClosingTransport(clock, [FakeConnection([RESET]), second])
    stream = StreamSession(transport, session, clock, URL, rand=lambda: 0.0)
    stream.open()
    result = stream.next_event()
    assert isinstance(result, Err)
    assert isinstance(result.error, StreamClosedError)
    assert second.closed
    assert second.sent == []


def test_candles_date_a_gap_by_when_they_were_read() -> None:
    # A bar's time is its start; an hourly bar updated all hour would date the gap an hour early.
    bar = json.dumps(
        {
            "destination": "ohlc.event",
            "payload": {
                "resolution": "HOUR",
                "epic": "GOLD",
                "type": "classic",
                "priceType": "bid",
                "t": EPOCH_MS,
                "o": 1,
                "h": 1,
                "l": 1,
                "c": 1,
            },
        }
    )
    first = FakeConnection([bar, RESET])
    stream, _, clock, _ = open_stream([first, FakeConnection([], auto_ack)])
    clock.advance(100)
    next_value(stream)
    gap = next_value(stream)
    assert isinstance(gap, Gap)
    assert gap.since == EPOCH + timedelta(seconds=100)


def test_consecutive_gaps_do_not_overlap() -> None:
    second = FakeConnection([], auto_ack)
    stream, _, _, _ = open_stream([FakeConnection([RESET]), second, FakeConnection([], auto_ack)])
    first_gap = next_value(stream)
    second.then(RESET)
    second_gap = next_value(stream)
    assert isinstance(first_gap, Gap)
    assert isinstance(second_gap, Gap)
    assert second_gap.since == first_gap.until


def test_close_during_resubscription_closes_the_new_connection() -> None:
    def closing_ack(frame: dict[str, Any]) -> list[str]:
        stream.close()
        return auto_ack(frame)

    first = FakeConnection([ack_frame("1", {"GOLD": "PROCESSED"}), RESET])
    second = FakeConnection([], closing_ack)
    stream, _, _, _ = open_stream([first, second])
    stream.subscribe_quotes(["GOLD"])
    result = stream.next_event()
    assert isinstance(result, Err)
    assert isinstance(result.error, StreamClosedError)
    assert second.closed


def test_a_subscribe_failing_otherwise_leaves_no_unconfirmed_keys() -> None:
    # A malformed frame no longer fails a subscribe (it is queued), so the "otherwise" failure
    # is a login refused for the stream twice.
    refused = [ack_frame(n, status="ERROR", error_code=INVALID_SESSION) for n in ("1", "2")]
    stream, _, _, _ = open_stream([FakeConnection(refused)])
    result = stream.subscribe_quotes(["OIL"])
    assert isinstance(result, Err)
    assert isinstance(result.error, AuthenticationError)
    assert stream.subscriptions.quotes == ()


def test_use_from_a_second_thread_is_refused() -> None:
    seen: list[object] = []

    class Interleaved(FakeConnection):
        def receive(self, timeout_s: float) -> "Result[str | None, TransportError]":
            # Same thread, but the session is busy, exactly as for a second thread.
            if seen:
                return super().receive(timeout_s)
            seen.append(stream.subscribe_quotes(["OIL"]))
            return Ok(quote_frame("A"))

    stream, _, _, _ = open_stream([Interleaved()])
    stream.next_event()
    (refused,) = seen
    assert isinstance(refused, Err)
    assert isinstance(refused.error, ValidationError)
    assert "thread" in str(refused.error)
