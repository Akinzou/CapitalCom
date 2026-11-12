"""Who closed a WebSocket decides the gap reason: only a server's close frame is SERVER_CLOSED."""

from websockets.exceptions import ConnectionClosed
from websockets.frames import Close

from capitalcom.infrastructure.websocket_transport import _closed


def test_close_started_by_us_is_not_reached_server() -> None:
    # Our side sent its close first (e.g. the library closing on a protocol error); the
    # server's frame is only the answer to it.
    ours = ConnectionClosed(Close(1000, ""), Close(1009, ""), rcvd_then_sent=False)
    assert _closed(ours).reached_server is False
    theirs = ConnectionClosed(Close(1000, ""), Close(1000, ""), rcvd_then_sent=True)
    assert _closed(theirs).reached_server is True
    received_only = ConnectionClosed(Close(1001, ""), None)
    assert _closed(received_only).reached_server is True
    neither = ConnectionClosed(None, None)
    assert _closed(neither).reached_server is False
