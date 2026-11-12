"""Ports: the process boundaries the core needs: HTTP, the WebSocket stream and the clock."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from capitalcom.application.json_codec import decode_json
from capitalcom.application.result import Result
from capitalcom.domain.errors import ResponseFormatError, TransportError


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """A request relative to the environment's base URL."""

    method: str
    path: str
    headers: Mapping[str, str] = field(default_factory=dict)
    params: Mapping[str, str] = field(default_factory=dict)
    json: Mapping[str, Any] | None = None

    def __repr__(self) -> str:
        # Headers carry the API key and session tokens, and the session body carries the
        # password, so the repr shows only what identifies the call.
        return f"HttpRequest({self.method} {self.path})"


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """A response as received; the status is not interpreted here."""

    status: int
    headers: Mapping[str, str]
    body: bytes

    def __repr__(self) -> str:
        # Login responses carry session tokens in their headers.
        return f"HttpResponse({self.status}, {len(self.body)} bytes)"

    def header(self, name: str) -> str | None:
        """Return a header value, matching the name case-insensitively."""
        wanted = name.lower()
        return next((v for k, v in self.headers.items() if k.lower() == wanted), None)

    def json(self) -> Any:  # noqa: ANN401 - JSON is untyped until a domain parser reads it
        """Decode the body; a body that is not JSON raises ``ResponseFormatError``."""
        try:
            return decode_json(self.body)
        except ValueError:
            text = self.body.decode("utf-8", errors="replace")
            raise ResponseFormatError(self.status, None, text) from None


class HttpTransport(Protocol):
    """Sends one HTTP request; never raises for network failures."""

    def send(self, request: HttpRequest) -> Result[HttpResponse, TransportError]:
        """Return the response, or ``TransportError`` when no HTTP response arrived."""
        ...


class Clock(Protocol):
    """Time source, injected so tests never sleep and never depend on the wall clock."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin; never goes backwards."""
        ...

    def now_utc(self) -> datetime:
        """Current time as an aware UTC datetime."""
        ...

    def sleep(self, seconds: float) -> None:
        """Block the calling thread."""
        ...


class StreamConnection(Protocol):
    """One open WebSocket; never raises for network failures."""

    def send(self, text: str) -> Result[None, TransportError]:
        """Send one text frame."""
        ...

    def receive(self, timeout_s: float) -> Result[str | None, TransportError]:
        """Wait up to ``timeout_s`` for one text frame; ``None`` when the time ran out."""
        ...

    def close(self) -> None:
        """Close the socket; never raises."""
        ...


class StreamTransport(Protocol):
    """Opens WebSocket connections."""

    def connect(self, url: str) -> Result[StreamConnection, TransportError]:
        """Open ``url``, or return ``TransportError`` when the handshake failed."""
        ...
