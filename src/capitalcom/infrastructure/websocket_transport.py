"""WebSocket transport over the ``websockets`` synchronous client (the ``streaming`` extra)."""

import logging
import ssl
from contextlib import ExitStack
from urllib.parse import urlsplit

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
            _log.debug("closing the stream socket failed: %s", type(error).__name__)


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
        context = ssl.create_default_context(cafile=self._cafile)
        # Entered as a context manager, the form every websockets release since 15 accepts
        # without a warning; the stack's close is the connection's close.
        stack = ExitStack()
        try:
            connection = stack.enter_context(
                connect(url, ssl=context, open_timeout=OPEN_TIMEOUT_S, logger=_log)
            )
        except (OSError, WebSocketException) as error:
            stack.close()
            return Err(TransportError(f"stream connect failed: {error}", reached_server=False))
        return Ok(WebsocketConnection(connection, stack))


def _closed(closed: ConnectionClosed) -> TransportError:
    # A close frame from the server means it ended the stream; without one the network did.
    if closed.rcvd is not None:
        return TransportError(f"stream closed by the server (code {closed.rcvd.code})")
    return TransportError("stream connection lost", reached_server=False)
