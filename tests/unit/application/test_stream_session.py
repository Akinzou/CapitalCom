"""The stream session: subscriptions, reconnects with backoff, gaps and account switches.

Every connection script ends in a terminal item or is read no further than scripted, since an
exhausted script is endless silence.
"""

from datetime import timedelta

from capitalcom.application.result import Err, Ok
from capitalcom.application.stream_session import StreamSession
from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import (
    AuthenticationError,
    StreamError,
    SubscriptionError,
    TransportError,
    ValidationError,
)
from capitalcom.domain.streaming import CandleType, Gap, GapReason, Quote
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

INVALID = "error.invalid.session.token"
RESET = TransportError("reset", reached_server=False)
M1, M5 = Resolution.MINUTE, Resolution.MINUTE_5


def test_subscribe_sends_only_new_keys_and_refused_keys_leave_the_set() -> None:
    connection = FakeConnection(
        [
            ack_frame("1", {"GOLD": "PROCESSED", "OIL": "PROCESSED"}),
            ack_frame("2", {"NOPE": "ERROR: NOPE not found", "SILVER": "PROCESSED"}),
        ]
    )
    stream, _, _, _ = open_stream([connection])
    assert stream.subscribe_quotes(["GOLD", "OIL"]) == Ok(None)
    refused = stream.subscribe_quotes(["GOLD", "NOPE", "SILVER"])
    assert isinstance(refused, Err)
    assert isinstance(refused.error, SubscriptionError)
    assert connection.sent[1]["payload"] == {"epics": ["NOPE", "SILVER"]}
    assert stream.subscriptions.quotes == ("GOLD", "OIL", "SILVER")
    assert stream.subscribe_quotes(["GOLD"]) == Ok(None)
    assert len(connection.sent) == 2


def test_ohlc_refusal_under_a_bare_epic_keeps_its_quotes() -> None:
    connection = FakeConnection(
        [
            ack_frame("1", {"GOLD": "PROCESSED"}),
            ack_frame("2", {"GOLD": "ERROR: Max Subscription limit reached."}),
        ]
    )
    stream, _, _, _ = open_stream([connection])
    stream.subscribe_quotes(["GOLD"])
    assert isinstance(stream.subscribe_ohlc(["GOLD"], [M1], CandleType.CLASSIC), Err)
    assert stream.subscriptions.quotes == ("GOLD",)
    assert stream.subscriptions.ohlc == ()


def test_local_validation_is_an_err_and_sends_nothing() -> None:
    connection = FakeConnection()
    stream, _, _, _ = open_stream([connection])
    result = stream.subscribe_quotes([])
    assert isinstance(result, Err)
    assert isinstance(result.error, ValidationError)
    assert connection.sent == []


def test_unsubscribe_sends_and_forgets() -> None:
    connection = FakeConnection([], auto_ack)
    stream, _, _, _ = open_stream([connection])
    stream.subscribe_quotes(["GOLD", "OIL"])
    stream.subscribe_ohlc(["GOLD"], [M1, M5], CandleType.CLASSIC)
    assert stream.unsubscribe_quotes(["OIL"]) == Ok(None)
    assert stream.unsubscribe_ohlc(["GOLD"], [M5], None) == Ok(None)
    assert connection.sent[2]["payload"] == {"epics": ["OIL"]}
    assert connection.sent[3]["payload"] == {"epics": ["GOLD"], "resolutions": ["MINUTE_5"]}
    assert stream.subscriptions.quotes == ("GOLD",)
    assert [k.wire() for k in stream.subscriptions.ohlc] == ["GOLD:MINUTE:classic"]


def test_drop_reconnects_resubscribes_and_yields_gap() -> None:
    first = FakeConnection([ack_frame("1", {"GOLD": "PROCESSED"}), quote_frame("A"), RESET])
    second = FakeConnection([quote_frame("B")], auto_ack)
    stream, transport, clock, _ = open_stream([first, second])
    stream.subscribe_quotes(["GOLD"])
    clock.advance(3)
    quote = next_value(stream)
    assert isinstance(quote, Quote)
    gap = next_value(stream)
    assert gap == Gap(
        EPOCH + timedelta(seconds=3), EPOCH + timedelta(seconds=3.5), GapReason.NETWORK
    )
    after = next_value(stream)
    assert isinstance(after, Quote)
    assert after.epic == "B"
    assert first.closed
    assert second.sent[0]["payload"] == {"epics": ["GOLD"]}
    assert transport.urls == [URL, URL]
    assert clock.sleeps == [0.5]


def test_events_before_drop_precede_gap() -> None:
    first = FakeConnection([ack_frame("1", {"GOLD": "PROCESSED"}), quote_frame("C")])
    second = FakeConnection([quote_frame("D")], auto_ack)
    stream, _, _, _ = open_stream([first, second])
    stream.subscribe_quotes(["GOLD"])
    assert stream.subscribe_quotes(["OIL"]) == Ok(None)
    order = [next_value(stream) for _ in range(3)]
    assert [type(e).__name__ for e in order] == ["Quote", "Gap", "Quote"]
    assert [e.epic for e in order if isinstance(e, Quote)] == ["C", "D"]


def test_subscribe_ack_timeout_reconnects_and_keeps_intent() -> None:
    first = FakeConnection([ack_frame("1", {"GOLD": "PROCESSED"})])
    second = FakeConnection([], auto_ack)
    stream, _, _, _ = open_stream([first, second])
    stream.subscribe_quotes(["GOLD"])
    assert stream.subscribe_quotes(["OIL"]) == Ok(None)
    assert second.sent[0]["payload"] == {"epics": ["GOLD", "OIL"]}
    gap = next_value(stream)
    assert isinstance(gap, Gap)
    assert gap.reason is GapReason.NETWORK


def test_server_close_gives_server_closed_reason() -> None:
    first = FakeConnection([TransportError("closed by the server", reached_server=True)])
    stream, _, _, _ = open_stream([first, FakeConnection([], auto_ack)])
    gap = next_value(stream)
    assert isinstance(gap, Gap)
    assert gap.reason is GapReason.SERVER_CLOSED


def test_backoff_sleeps_follow_policy() -> None:
    first = FakeConnection([RESET])
    last = FakeConnection([], auto_ack)
    stream, transport, clock, _ = open_stream([first, RESET, RESET, RESET, RESET, last])
    assert isinstance(next_value(stream), Gap)
    assert clock.sleeps == [0.5, 1.0, 2.0, 4.0, 8.0]
    assert len(transport.urls) == 6


def test_five_failures_raise_stream_error_with_cause() -> None:
    refused = TransportError("connection refused", reached_server=False)
    stream, transport, _, _ = open_stream([FakeConnection([RESET]), refused])
    result = stream.next_event()
    assert isinstance(result, Err)
    assert isinstance(result.error, StreamError)
    assert result.error.__cause__ is refused
    assert len(transport.urls) == 6
    closed = stream.next_event()
    assert isinstance(closed, Err)
    assert isinstance(closed.error, ValidationError)


def test_auth_error_on_reconnect_is_not_retried() -> None:
    refusal = ack_frame("1", status="ERROR", error_code=INVALID)
    second = FakeConnection([refusal, ack_frame("2", status="ERROR", error_code=INVALID)])
    first = FakeConnection([ack_frame("1", {"GOLD": "PROCESSED"}), RESET])
    stream, transport, _, _ = open_stream([first, second])
    stream.subscribe_quotes(["GOLD"])
    result = stream.next_event()
    assert isinstance(result, Err)
    assert isinstance(result.error, AuthenticationError)
    assert len(transport.urls) == 2
    assert second.closed


def test_refusal_on_resubscribe_closes_and_raises() -> None:
    first = FakeConnection([ack_frame("1", {"GOLD": "PROCESSED"}), RESET])
    second = FakeConnection([ack_frame("1", {"GOLD": "ERROR: GOLD not found"})])
    stream, _, _, _ = open_stream([first, second])
    stream.subscribe_quotes(["GOLD"])
    result = stream.next_event()
    assert isinstance(result, Err)
    assert isinstance(result.error, SubscriptionError)
    assert second.closed
    assert isinstance(stream.subscribe_quotes(["OIL"]), Err)


def test_account_switch_reconnects_with_account_switched_reason() -> None:
    first = FakeConnection([], auto_ack)
    second = FakeConnection([quote_frame("E")], auto_ack)
    stream, _, _, session = open_stream([first, second], accounts=["A", "B"])
    stream.subscribe_quotes(["GOLD"])
    tokens = session.current_tokens()
    assert tokens is not None
    session.invalidate(tokens)
    session.tokens()
    gap = next_value(stream)
    assert isinstance(gap, Gap)
    assert gap.reason is GapReason.ACCOUNT_SWITCHED
    assert first.closed
    assert second.sent[0]["payload"] == {"epics": ["GOLD"]}
    assert isinstance(next_value(stream), Quote)


def test_unknown_account_is_not_a_switch() -> None:
    first = FakeConnection([quote_frame("F")])
    stream, transport, _, session = open_stream([first], accounts=["A", "B"])
    tokens = session.current_tokens()
    assert tokens is not None
    session.invalidate(tokens)
    assert isinstance(next_value(stream), Quote)
    assert len(transport.urls) == 1


def test_ohlc_resubscribe_groups_by_exact_resolution_set() -> None:
    first = FakeConnection([], auto_ack)
    second = FakeConnection([], auto_ack)
    stream, _, _, _ = open_stream([first, second])
    stream.subscribe_ohlc(["A", "B"], [M1, M5], CandleType.CLASSIC)
    stream.unsubscribe_ohlc(["B"], [M5], None)
    first.then(RESET)  # the link drops after the setup frames
    assert isinstance(next_value(stream), Gap)
    payloads = sorted((f["payload"]["epics"], f["payload"]["resolutions"]) for f in second.sent)
    assert payloads == [(["A"], ["MINUTE", "MINUTE_5"]), (["B"], ["MINUTE"])]


def test_auth_error_while_streaming_closes_the_stream() -> None:
    first = FakeConnection(
        [
            ack_frame("1", status="ERROR", error_code=INVALID),
            ack_frame("2", status="ERROR", error_code=INVALID),
        ]
    )
    stream, _, clock, _ = open_stream([first])
    clock.advance(300)
    result = stream.next_event()
    assert isinstance(result, Err)
    assert isinstance(result.error, AuthenticationError)
    assert first.closed


def test_close_closes_the_socket_and_refuses_calls() -> None:
    first = FakeConnection()
    stream, _, _, _ = open_stream([first])
    stream.close()
    stream.close()
    assert first.closed
    assert isinstance(stream.subscribe_quotes(["GOLD"]), Err)
    assert isinstance(stream.next_event(), Err)


def test_open_failure_is_returned_without_retries() -> None:
    clock = FakeClock()
    session, _ = make_session(clock)
    refused = TransportError("connection refused", reached_server=False)
    transport = FakeStreamTransport(clock, [refused])
    stream = StreamSession(transport, session, clock, URL)
    assert stream.open() == Err(refused)
    assert clock.sleeps == []
    assert isinstance(stream.next_event(), Err)


def test_open_twice_is_refused() -> None:
    stream, transport, _, _ = open_stream([FakeConnection()])
    result = stream.open()
    assert isinstance(result, Err)
    assert isinstance(result.error, ValidationError)
    assert len(transport.urls) == 1
