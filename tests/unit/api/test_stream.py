"""``cc.stream``: the public stream raises what the session returns and owns one socket."""

import itertools
import json
import sys
from typing import Any

import pytest

from capitalcom.api.composition import Core, build_core, stream_transport
from capitalcom.api.stream import Stream, StreamResource
from capitalcom.application.ports import StreamTransport
from capitalcom.application.result import Err, Result
from capitalcom.application.session import Credentials
from capitalcom.application.stream_gaps import kept_from_drop
from capitalcom.domain.enums import STREAM_URL, Environment, Resolution
from capitalcom.domain.errors import (
    StreamError,
    SubscriptionError,
    TransportError,
    ValidationError,
)
from capitalcom.domain.secret import Secret
from capitalcom.domain.streaming import Candle, CandleType, Gap, Quote
from tests.fakes import (
    FakeClock,
    FakeConnection,
    FakeStreamTransport,
    FakeTransport,
    Silence,
    ack_frame,
    auto_ack,
    quote_frame,
)
from tests.unit.application.stream_support import login_ok

RESET = TransportError("reset", reached_server=False)
CANDLE = json.dumps(
    {
        "destination": "ohlc.event",
        "payload": {
            "resolution": "MINUTE",
            "epic": "GOLD",
            "type": "classic",
            "priceType": "bid",
            "t": 1794446400000,
            "o": "1",
            "h": "2",
            "l": "0.5",
            "c": "1.5",
        },
    }
)


def resource(
    connections: list[FakeConnection | TransportError],
) -> tuple[StreamResource, FakeStreamTransport, Core]:
    clock = FakeClock()
    credentials = Credentials(Secret("str-key-0001"), "me@example.com", Secret("str-pw-0001"))
    http = FakeTransport([login_ok(n) for n in range(1, 4)])
    core = build_core(credentials, Environment.DEMO, clock=clock, transport=http)
    transport = FakeStreamTransport(clock, connections)
    return StreamResource(core, lambda: transport), transport, core


def test_connect_dials_the_pinned_url_and_logs_in() -> None:
    streams, transport, core = resource([FakeConnection()])
    with streams.connect() as stream:
        assert isinstance(stream, Stream)
    assert transport.urls == [STREAM_URL]
    assert core.session.current_tokens() is not None


def test_iteration_yields_quotes_candles_and_gaps() -> None:
    first = FakeConnection(
        [ack_frame("1", {"GOLD": "PROCESSED"}), quote_frame("GOLD"), CANDLE, RESET]
    )
    streams, _, _ = resource([first, FakeConnection([], auto_ack)])
    with streams.connect() as stream:
        stream.subscribe_quotes(["GOLD"])
        events = list(itertools.islice(stream, 3))
    assert [type(e) for e in events] == [Quote, Candle, Gap]


def test_errors_are_raised_not_returned() -> None:
    refused = FakeConnection([ack_frame("1", {"NOPE": "ERROR: NOPE not found"})])
    streams, _, _ = resource([refused])
    with streams.connect() as stream:
        with pytest.raises(SubscriptionError, match="NOPE not found"):
            stream.subscribe_quotes(["NOPE"])
        with pytest.raises(ValidationError):
            stream.subscribe_quotes([])


def test_ohlc_defaults_are_classic_minute_bars() -> None:
    connection = FakeConnection([], auto_ack)
    streams, _, _ = resource([connection])
    with streams.connect() as stream:
        stream.subscribe_ohlc(["GOLD"])
        stream.subscribe_ohlc(["GOLD"], [Resolution.HOUR], CandleType.HEIKIN_ASHI)
        stream.unsubscribe_ohlc(["GOLD"], candles=[CandleType.CLASSIC])
    first, _, third = (frame["payload"] for frame in connection.sent)
    assert first == {"epics": ["GOLD"], "resolutions": ["MINUTE"], "type": "classic"}
    assert third == {"epics": ["GOLD"], "types": ["classic"]}


def test_second_connect_raises() -> None:
    streams, transport, _ = resource([FakeConnection(), FakeConnection()])
    first = streams.connect()
    with pytest.raises(ValidationError, match="one stream"):
        streams.connect()
    first.close()
    streams.connect().close()
    assert len(transport.urls) == 2


def test_methods_on_closed_stream_raise_and_next_stops() -> None:
    connection = FakeConnection([], auto_ack)
    streams, _, _ = resource([connection])
    stream = streams.connect()
    stream.close()
    assert connection.closed
    with pytest.raises(ValidationError, match="closed"):
        stream.subscribe_quotes(["GOLD"])
    with pytest.raises(ValidationError, match="closed"):
        stream.unsubscribe_quotes(["GOLD"])
    assert list(stream) == []


def test_a_stream_that_gave_up_stops_and_frees_the_slot() -> None:
    refused = TransportError("connection refused", reached_server=False)
    streams, _, _ = resource([FakeConnection([RESET]), refused])
    stream = streams.connect()
    with pytest.raises(StreamError):
        next(stream)
    with pytest.raises(StopIteration):
        next(stream)
    with pytest.raises(TransportError):
        streams.connect()


def test_missing_extra_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every cached websockets module is blocked: a cached submodule would import without
    # its parent package being looked up again.
    for name in [n for n in sys.modules if n == "websockets" or n.startswith("websockets.")]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "websockets", None)
    monkeypatch.delitem(sys.modules, "capitalcom.infrastructure.websocket_transport", False)
    with pytest.raises(ImportError, match=r"capitalcom\[streaming\]"):
        stream_transport(None)


def test_stream_transport_keeps_a_ca_bundle_from_the_session() -> None:
    import requests

    from capitalcom.infrastructure.websocket_transport import WebsocketTransport

    session = requests.Session()
    session.verify = "/path/to/bundle.pem"
    transport: StreamTransport = stream_transport(session)
    assert isinstance(transport, WebsocketTransport)
    assert transport._cafile == "/path/to/bundle.pem"
    assert stream_transport(None)._cafile is None  # type: ignore[attr-defined]


def test_a_close_from_another_thread_ends_iteration() -> None:
    holder: list[Stream] = []

    class ClosedMidRead(FakeConnection):
        def receive(self, timeout_s: float) -> Result[str | None, TransportError]:
            holder[0].close()  # what a close() from another thread looks like to the reader
            return Err(TransportError("closed by this client", reached_server=True))

    streams, transport, _ = resource([ClosedMidRead(), FakeConnection([], auto_ack)])
    holder.append(streams.connect())
    assert list(holder[0]) == []
    assert len(transport.urls) == 1


def test_stream_trusts_the_same_bundle_as_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    # REST passes the session's bundle explicitly, so it beats the environment; a stream
    # that let REQUESTS_CA_BUNDLE win would silently trust a wider set than the user chose.
    import requests

    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/etc/ssl/certs")
    assert stream_transport(None)._cafile == "/etc/ssl/certs"  # type: ignore[attr-defined]
    session = requests.Session()
    session.verify = "/path/to/bundle.pem"
    assert stream_transport(session)._cafile == "/path/to/bundle.pem"  # type: ignore[attr-defined]
    session.verify = False  # never switches checks off: the environment's bundle, as in REST
    assert stream_transport(session)._cafile == "/etc/ssl/certs"  # type: ignore[attr-defined]
    session.trust_env = False
    assert stream_transport(session)._cafile is None  # type: ignore[attr-defined]


REFUSED = TransportError("connection refused", reached_server=False)


def _dropped_with_two_quotes_in_the_drain(core: Core) -> None:
    # The keepalive ack is overdue, so the drain reads A and B into the link's buffer before
    # the drop: exactly the events a give-up used to throw away.
    assert isinstance(core.clock, FakeClock)
    core.clock.advance(300)


def _drain_script() -> FakeConnection:
    return FakeConnection(
        [
            ack_frame("1", {"GOLD": "PROCESSED"}),
            Silence(10),
            quote_frame("A"),
            quote_frame("B"),
            RESET,
        ]
    )


def test_give_up_in_next_delivers_buffered_events_then_raises() -> None:
    streams, _, core = resource([_drain_script(), REFUSED])
    stream = streams.connect()
    stream.subscribe_quotes(["GOLD"])
    _dropped_with_two_quotes_in_the_drain(core)
    assert [e.epic for e in itertools.islice(stream, 2) if isinstance(e, Quote)] == ["A", "B"]
    with pytest.raises(StreamError):
        next(stream)
    with pytest.raises(StopIteration):
        next(stream)


def test_refused_resubscription_also_keeps_buffered_events() -> None:
    refusal = FakeConnection([ack_frame("1", {"GOLD": "ERROR: GOLD not found"})])
    streams, _, core = resource([_drain_script(), refusal])
    stream = streams.connect()
    stream.subscribe_quotes(["GOLD"])
    _dropped_with_two_quotes_in_the_drain(core)
    assert len(list(itertools.islice(stream, 2))) == 2
    with pytest.raises(SubscriptionError):
        next(stream)
    assert list(stream) == []


def _gave_up_in_subscribe(
    after: list[FakeConnection | TransportError],
) -> tuple[StreamResource, Stream]:
    streams, _, _ = resource([FakeConnection([quote_frame("A"), RESET]), *[REFUSED] * 5, *after])
    stream = streams.connect()
    with pytest.raises(StreamError):
        stream.subscribe_quotes(["GOLD"])
    return streams, stream


def test_give_up_in_subscribe_keeps_events_without_a_second_raise() -> None:
    _, stream = _gave_up_in_subscribe([REFUSED])
    assert stream.closed
    events = list(stream)
    assert [e.epic for e in events if isinstance(e, Quote)] == ["A"]
    assert len(events) == 1


def test_explicit_close_discards_buffered_events() -> None:
    _, stream = _gave_up_in_subscribe([REFUSED])
    stream.close()
    assert list(stream) == []


def test_connect_allowed_after_give_up_while_events_remain() -> None:
    streams, stream = _gave_up_in_subscribe([FakeConnection()])
    with streams.connect() as fresh:
        assert not fresh.closed
    assert len(list(stream)) == 1


def test_a_close_from_another_thread_during_a_drop_ends_iteration_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams, _, core = resource([_drain_script(), REFUSED])
    stream = streams.connect()
    stream.subscribe_quotes(["GOLD"])

    def closed_inside_the_window(*args: Any) -> Any:
        stream.close()  # another thread's close() landing between the check and the use
        return kept_from_drop(*args)

    target = "capitalcom.application.stream_session.kept_from_drop"
    monkeypatch.setattr(target, closed_inside_the_window)
    _dropped_with_two_quotes_in_the_drain(core)
    assert list(stream) == []  # no AttributeError, and nothing delivered after the close
