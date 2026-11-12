"""A frame that cannot be decoded is raised in arrival order and never aborts an ack wait."""

from capitalcom.application.result import Err, Ok
from capitalcom.application.stream_session import StreamSession
from capitalcom.domain.errors import ResponseFormatError, TransportError
from capitalcom.domain.streaming import Gap, GapReason, Quote
from tests.fakes import FakeConnection, ack_frame, auto_ack, quote_frame
from tests.unit.application.stream_support import next_value, open_stream

RESET = TransportError("reset", reached_server=False)


def _next_error(stream: StreamSession) -> object:
    result = stream.next_event()
    assert isinstance(result, Err), result
    return result.error


def test_malformed_frame_during_subscribe_is_raised_in_order() -> None:
    first = FakeConnection(["not json", ack_frame("1", {"GOLD": "PROCESSED"}), quote_frame("GOLD")])
    stream, _, _, _ = open_stream([first])
    assert stream.subscribe_quotes(["GOLD"]) == Ok(None)
    assert isinstance(_next_error(stream), ResponseFormatError)
    assert isinstance(next_value(stream), Quote)


def test_malformed_frame_during_resubscription_keeps_the_stream() -> None:
    first = FakeConnection([ack_frame("1", {"GOLD": "PROCESSED"}), RESET])
    second = FakeConnection(["not json"], auto_ack)
    stream, _, _, _ = open_stream([first, second])
    assert stream.subscribe_quotes(["GOLD"]) == Ok(None)
    # The frame arrived on the new connection, after the drop the Gap stands for.
    assert isinstance(next_value(stream), Gap)
    assert isinstance(_next_error(stream), ResponseFormatError)
    assert stream.closed is False
    assert stream.subscriptions.quotes == ("GOLD",)


def test_malformed_ack_times_out_into_a_network_gap() -> None:
    first = FakeConnection(["not json"])
    stream, _, _, _ = open_stream([first, FakeConnection([], auto_ack)])
    assert stream.subscribe_quotes(["GOLD"]) == Ok(None)
    assert isinstance(_next_error(stream), ResponseFormatError)
    gap = next_value(stream)
    assert isinstance(gap, Gap)
    assert gap.reason is GapReason.NETWORK
    assert stream.closed is False
