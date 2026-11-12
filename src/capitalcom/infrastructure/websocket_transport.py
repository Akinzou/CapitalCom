"""WebSocket transport over the ``websockets`` synchronous client (the ``streaming`` extra)."""

import logging
import ssl
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

from requests.utils import DEFAULT_CA_BUNDLE_PATH
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import ClientConnection, connect

from capitalcom.application.logs import get_logger
from capitalcom.application.ports import StreamConnection
from capitalcom.application.result import Err, Ok, Result
from capitalcom.domain.errors import TransportError, ValidationError

OPEN_TIMEOUT_S = 10.0
# The library's frame dumps ("> %s", "< %s") are cut to a fixed length. Masking replaces
# whole tokens only, so a token cut in half would show its other half; the dumps are dropped.
_FRAME_DUMPS = frozenset({"> %s", "< %s"})


class _DropFrameDumps(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.msg not in _FRAME_DUMPS


_log = get_logger("capitalcom.websocket")
_log.addFilter(_DropFrameDumps())
# Every DEBUG record of the library is withheld, not only the dumps the filter knows: a
# release that rewords its frame dump must not start leaking token fragments.
_log.setLevel(logging.INFO)

_stream_log = get_logger("capitalcom.stream")

# Kept as a module name so tests can see the arguments the context is built with.
_default_context = ssl.create_default_context


class WebsocketConnection:
    """One open socket; every failure comes back as ``TransportError``."""

    def __init__(self, connection: ClientConnection, stack: ExitStack) -> None:
        self._connection = connection
        self._stack = stack

    def send(self, text: str) -> Result[None, TransportError]:
        """Send one text frame."""
        try:
            self._connection.send(text)
        except ConnectionClosed as closed:
            return Err(_closed(closed))
        except OSError as error:
            return Err(TransportError(f"stream send failed: {error}", reached_server=False))
        return Ok(None)

    def receive(self, timeout_s: float) -> Result[str | None, TransportError]:
        """Wait up to ``timeout_s`` for a frame; ``None`` when none arrived in time."""
        try:
            message = self._connection.recv(timeout=timeout_s)
        except TimeoutError:
            return Ok(None)
        except ConnectionClosed as closed:
            return Err(_closed(closed))
        except OSError as error:
            return Err(TransportError(f"stream receive failed: {error}", reached_server=False))
        if isinstance(message, bytes):
            return Ok(message.decode("utf-8", errors="replace"))
        return Ok(message)

    def close(self) -> None:
        """Close the socket; a failure to close is logged, never raised."""
        try:
            self._stack.close()
        except (OSError, WebSocketException) as error:
            # On the stream logger: the websockets logger withholds DEBUG, and a failure here
            # must still be visible.
            _stream_log.warning("closing the stream socket failed: %s", type(error).__name__)


class WebsocketTransport:
    """Opens ``wss`` connections with TLS always verified."""

    def __init__(self, verify: bool | str = True) -> None:
        if verify is not True and not (isinstance(verify, str) and verify):
            raise ValidationError("TLS verification cannot be switched off for the stream")
        self._cafile = verify if isinstance(verify, str) else None

    def connect(self, url: str) -> Result[StreamConnection, TransportError]:
        """Open ``url``; a refused handshake or certificate is a ``TransportError``."""
        if urlsplit(url).scheme != "wss":
            raise ValidationError("the stream URL must use wss")
        # Entered as a context manager, the form every websockets release since 15 accepts
        # without a warning; the stack's close is the connection's close.
        stack = ExitStack()
        try:
            context = self._context()
            connection = stack.enter_context(
                connect(
                    url,
                    ssl=context,
                    open_timeout=OPEN_TIMEOUT_S,
                    # The library's own keepalive is off: once its receive queue is full it
                    # stops reading, misses its pongs and drops a link that is merely busy.
                    # The stream's ping every 5 minutes, with its 10 s ack timeout, replaces it.
                    ping_interval=None,
                    logger=_log,
                )
            )
        except (OSError, WebSocketException) as error:
            stack.close()
            return Err(TransportError(f"stream connect failed: {error}", reached_server=False))
        return Ok(WebsocketConnection(connection, stack))

    def _context(self) -> ssl.SSLContext:
        # The same trust as the REST transport: the bundle or directory chosen by the
        # composition root with requests' rules, else requests' own bundle. The system store
        # alone would fail on some installs where REST works.
        if self._cafile is not None and Path(self._cafile).is_dir():
            return _default_context(cafile=None, capath=self._cafile)
        return _default_context(cafile=self._cafile or DEFAULT_CA_BUNDLE_PATH)


def _closed(closed: ConnectionClosed) -> TransportError:
    # Only a close the server started means it ended the stream. When our side closed first
    # (rcvd_then_sent is False: the library closing on a protocol error, say), the server's
    # frame merely answered it; without any frame the network ended it.
    if closed.rcvd is not None and closed.rcvd_then_sent is not False:
        return TransportError(f"stream closed by the server (code {closed.rcvd.code})")
    return TransportError("stream connection lost", reached_server=False)
