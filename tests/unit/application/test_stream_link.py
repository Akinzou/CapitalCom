"""One stream connection: acknowledged requests, buffered events and the keepalive."""

import pytest

from capitalcom.application.result import Err, Ok
from capitalcom.application.stream_frames import Ack, Event
from capitalcom.application.stream_link import (
    ACK_TIMEOUT_S,
    DRAIN_MAX_FRAMES,
    KEEPALIVE_S,
    AckTimeoutError,
    StreamLink,
)
from capitalcom.domain.errors import (
    AuthenticationError,
    ResponseFormatError,
    SubscriptionError,
    TransportError,
)
from tests.fakes import (
    FakeClock,
    FakeConnection,
    FakeStreamTransport,
    Silence,
    StreamScript,
    ack_frame,
    auto_ack,
    quote_frame,
)
from tests.unit.application.stream_support import make_session

INVALID = "error.invalid.session.token"
SUBSCRIBE = "marketData.subscribe"


def open_link(
    script: StreamScript = (), *, responder: bool = False, logins: int = 3
) -> tuple[StreamLink, FakeConnection, FakeClock]:
    clock = FakeClock()
    session, _ = make_session(clock, logins)
    connection = FakeConnection(script, auto_ack if responder else None)
    connected = FakeStreamTransport(clock, [connection]).connect("wss://stream.test/connect")
    assert isinstance(connected, Ok)
    return StreamLink(connected.value, session, clock), connection, clock


def test_request_buffers_events_until_its_ack() -> None:
    link, connection, _ = open_link(
        [quote_frame("A"), quote_frame("B"), ack_frame("1", {"GOLD": "PROCESSED"})]
    )
    result = link.request(SUBSCRIBE, {"epics": ["GOLD"]}, ["GOLD"])
    assert isinstance(result, Ok)
    assert isinstance(result.value, Ack)
    assert connection.sent[0]["payload"] == {"epics": ["GOLD"]}
    first, second = link.next_incoming(), link.next_incoming()
    assert isinstance(first, Ok)
    assert isinstance(first.value, Event)
    assert isinstance(second, Ok)
    assert isinstance(second.value, Event)
    assert [first.value.value.epic, second.value.value.epic] == ["A", "B"]


def test_refused_key_is_subscription_error() -> None:
    link, _, _ = open_link([ack_frame("1", {"NOPE": "ERROR: NOPE not found"})])
    result = link.request(SUBSCRIBE, {"epics": ["NOPE"]}, ["NOPE"])
    assert isinstance(result, Err)
    assert isinstance(result.error, SubscriptionError)


def test_ack_timeout_is_transport_error() -> None:
    link, _, clock = open_link()
    result = link.request(SUBSCRIBE, {"epics": ["GOLD"]}, ["GOLD"])
    assert isinstance(result, Err)
    assert isinstance(result.error, TransportError)
    assert result.error.reached_server
    assert "acknowledgement" in str(result.error)
    assert clock.monotonic() == ACK_TIMEOUT_S


def test_other_acks_do_not_answer_a_request() -> None:
    link, _, _ = open_link([ack_frame("99"), ack_frame("1", {"GOLD": "PROCESSED"})])
    assert isinstance(link.request(SUBSCRIBE, {"epics": ["GOLD"]}, ["GOLD"]), Ok)


def test_invalid_session_invalidates_and_resends_once() -> None:
    link, connection, _ = open_link(
        [
            ack_frame("1", status="ERROR", error_code=INVALID),
            ack_frame("2", {"GOLD": "PROCESSED"}),
        ]
    )
    assert isinstance(link.request(SUBSCRIBE, {"epics": ["GOLD"]}, ["GOLD"]), Ok)
    assert [(f["correlationId"], f["cst"]) for f in connection.sent] == [
        ("1", "cst-1"),
        ("2", "cst-2"),
    ]


def test_second_invalid_session_is_authentication_error() -> None:
    link, _, _ = open_link(
        [
            ack_frame("1", status="ERROR", error_code=INVALID),
            ack_frame("2", status="ERROR", error_code=INVALID),
        ]
    )
    result = link.request(SUBSCRIBE, {"epics": ["GOLD"]}, ["GOLD"])
    assert isinstance(result, Err)
    assert isinstance(result.error, AuthenticationError)
    assert (result.error.status, result.error.error_code) == (401, INVALID)


def test_ping_sent_after_keepalive_interval_and_marks_session_used() -> None:
    link, connection, clock = open_link(responder=True)
    assert link.next_incoming() == Ok(None)
    assert clock.monotonic() == KEEPALIVE_S
    assert connection.sent == []
    assert link.next_incoming() == Ok(None)
    assert connection.destinations() == ["ping"]
    assert "payload" not in connection.sent[0]
    assert link._session.idle_remaining_s() == 600.0


def test_overdue_ping_is_sent_before_next_receive() -> None:
    link, connection, clock = open_link([quote_frame("A"), quote_frame("B")], responder=True)
    assert isinstance(link.next_incoming(), Ok)
    clock.advance(400)
    second = link.next_incoming()
    assert connection.destinations() == ["ping"]
    assert isinstance(second, Ok)
    assert isinstance(second.value, Event)
    assert second.value.value.epic == "B"


def test_missing_keepalive_ack_is_transport_error() -> None:
    link, connection, clock = open_link()
    clock.advance(KEEPALIVE_S)
    results = [link.next_incoming() for _ in range(2)]
    assert results[0] == Ok(None)
    assert isinstance(results[1], Err)
    assert isinstance(results[1].error, TransportError)
    assert "keepalive" in str(results[1].error)
    assert connection.destinations() == ["ping"]


def test_keepalive_with_refused_tokens_pings_again_with_fresh_ones() -> None:
    link, connection, clock = open_link(
        [ack_frame("1", status="ERROR", error_code=INVALID), ack_frame("2")]
    )
    clock.advance(KEEPALIVE_S)
    assert link.next_incoming() == Ok(None)
    assert link.next_incoming() == Ok(None)
    assert [f["cst"] for f in connection.sent] == ["cst-1", "cst-2"]
    third = link.next_incoming()
    assert third == Ok(None)
    assert clock.monotonic() == pytest.approx(2 * KEEPALIVE_S)


def test_frames_carry_current_tokens_after_renewal() -> None:
    link, connection, clock = open_link(responder=True)
    clock.advance(580)
    assert isinstance(link.request(SUBSCRIBE, {"epics": ["GOLD"]}, ["GOLD"]), Ok)
    assert connection.sent[0]["cst"] == "cst-2"


def test_unknown_destination_is_skipped() -> None:
    link, _, _ = open_link(['{"destination": "news", "payload": {}}', quote_frame("A")])
    assert link.next_incoming() == Ok(None)
    event = link.next_incoming()
    assert isinstance(event, Ok)
    assert isinstance(event.value, Event)


def test_malformed_frame_is_response_format_error() -> None:
    link, _, _ = open_link(["[]"])
    result = link.next_incoming()
    assert isinstance(result, Err)
    assert isinstance(result.error, ResponseFormatError)


def test_transport_error_is_returned() -> None:
    link, connection, _ = open_link([TransportError("reset", reached_server=False)])
    result = link.next_incoming()
    assert isinstance(result, Err)
    assert isinstance(result.error, TransportError)
    assert not result.error.reached_server
    link.close()
    assert connection.closed


def test_timeouts_are_ack_timeouts_not_server_closes() -> None:
    link, _, clock = open_link()
    request = link.request(SUBSCRIBE, {"epics": ["GOLD"]}, ["GOLD"])
    assert isinstance(request, Err)
    assert isinstance(request.error, AckTimeoutError)
    clock.advance(KEEPALIVE_S)
    link.next_incoming()
    keepalive = link.next_incoming()
    assert isinstance(keepalive, Err)
    assert isinstance(keepalive.error, AckTimeoutError)


def test_slow_consumer_does_not_miss_a_queued_keepalive_ack() -> None:
    link, _, clock = open_link([quote_frame("A"), ack_frame("1"), quote_frame("B")])
    clock.advance(KEEPALIVE_S)
    first = link.next_incoming()
    assert isinstance(first, Ok)
    assert isinstance(first.value, Event)
    clock.advance(15)
    second = link.next_incoming()
    assert isinstance(second, Ok)
    assert isinstance(second.value, Event)
    assert second.value.value.epic == "B"


def test_drain_hands_over_events_buffered_by_a_failed_request() -> None:
    link, _, _ = open_link([quote_frame("A")])
    assert isinstance(link.request(SUBSCRIBE, {"epics": ["GOLD"]}, ["GOLD"]), Err)
    assert [e.value.epic for e in link.drain()] == ["A"]
    assert link.drain() == []


def test_overdue_keepalive_ack_arriving_just_after_the_queue_empties_is_found() -> None:
    # A flow-controlled socket refills its queue only after it has been read from, so the
    # ack may be a moment behind the last queued frame.
    link, _, clock = open_link([quote_frame("A"), quote_frame("B"), Silence(0.5), ack_frame("1")])
    clock.advance(KEEPALIVE_S)
    assert isinstance(link.next_incoming(), Ok)
    clock.advance(15)
    result = link.next_incoming()
    assert isinstance(result, Ok)
    assert isinstance(result.value, Event)
    assert result.value.value.epic == "B"
    assert isinstance(link.next_incoming(), Ok)


def test_a_busy_feed_cannot_hide_a_missing_keepalive_ack_forever() -> None:
    link, _, clock = open_link([quote_frame(f"E{n}") for n in range(DRAIN_MAX_FRAMES + 50)])
    clock.advance(KEEPALIVE_S)
    assert isinstance(link.next_incoming(), Ok)
    clock.advance(15)
    result = link.next_incoming()
    assert isinstance(result, Err)
    assert isinstance(result.error, AckTimeoutError)
    assert len(link.drain()) <= DRAIN_MAX_FRAMES
