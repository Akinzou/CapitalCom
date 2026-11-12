"""``cc.stream``: the public stream raises what the session returns and owns one socket."""

import itertools
import json
import sys

import pytest

from capitalcom.api.composition import Core, build_core, stream_transport
from capitalcom.api.stream import Stream, StreamResource
from capitalcom.application.ports import StreamTransport
from capitalcom.application.result import Err, Result
from capitalcom.application.session import Credentials
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
