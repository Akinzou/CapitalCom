"""Gaps and closing: what ``since`` reports, and a close from another thread."""

from datetime import timedelta

from capitalcom.application.ports import StreamConnection
from capitalcom.application.result import Err, Result
from capitalcom.application.stream_session import StreamClosedError, StreamSession
from capitalcom.domain.errors import TransportError
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
