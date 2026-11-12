"""In-memory test doubles for the application ports. They never touch the network or sleep."""

import json
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from capitalcom.application.ports import HttpRequest, HttpResponse, StreamConnection
from capitalcom.application.result import Err, Ok, Result
from capitalcom.domain.errors import TransportError

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class FakeClock:
    """Time starts at 0 and moves only when ``sleep`` or ``advance`` is called."""

    def __init__(self) -> None:
        self._now = 0.0
        self._lock = threading.Lock()
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        with self._lock:
            return self._now

    def now_utc(self) -> datetime:
        with self._lock:
            return EPOCH + timedelta(seconds=self._now)

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleeps.append(seconds)
            self._now += seconds

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds


def response(
    status: int = 200, body: bytes = b"", headers: dict[str, str] | None = None
) -> HttpResponse:
    return HttpResponse(status, headers or {}, body)


class FakeTransport:
    """Replays a script of responses or transport errors and records every request.

    When the script runs out, the last entry repeats, so "always 404" needs one entry.
    """

    def __init__(self, script: Sequence[HttpResponse | TransportError]) -> None:
        self._script = list(script)
        self._lock = threading.Lock()
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> Result[HttpResponse, TransportError]:
        with self._lock:
            self.requests.append(request)
            item = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        if isinstance(item, TransportError):
            return Err(item)
        return Ok(item)


@dataclass(frozen=True)
class Silence:
    """The server sends nothing for ``seconds``; a receive waits at most its own timeout."""

    seconds: float


StreamScript = Sequence[str | TransportError | Silence]
Responder = Callable[[dict[str, Any]], list[str]]


class FakeConnection:
    """Replays scripted frames, errors and silences; records every sent frame as a dict.

    A responder's answers to a sent frame are queued behind what is already scripted, as a
    server answers after the frames already on the wire. An empty script is endless silence.
    """

    def __init__(self, script: StreamScript = (), responder: Responder | None = None) -> None:
        self._script: deque[str | TransportError | Silence] = deque(script)
        self._responder = responder
        self.clock: FakeClock | None = None
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def send(self, text: str) -> Result[None, TransportError]:
        frame = json.loads(text)
        self.sent.append(frame)
        if self._responder is not None:
            self._script.extend(self._responder(frame))
        return Ok(None)

    def receive(self, timeout_s: float) -> Result[str | None, TransportError]:
        assert self.clock is not None, "connect the fake through FakeStreamTransport"
        if not self._script:
            self.clock.advance(timeout_s)
            return Ok(None)
        item = self._script.popleft()
        if isinstance(item, TransportError):
            return Err(item)
        if isinstance(item, Silence):
            # Like a real receive, a silence shorter than the timeout does not end the wait.
            if item.seconds >= timeout_s:
                if item.seconds > timeout_s:
                    self._script.appendleft(Silence(item.seconds - timeout_s))
                self.clock.advance(timeout_s)
                return Ok(None)
            self.clock.advance(item.seconds)
            return self.receive(timeout_s - item.seconds)
        return Ok(item)

    def close(self) -> None:
        self.closed = True

    def then(self, *items: "str | TransportError | Silence") -> None:
        """Script more items after what is already queued."""
        self._script.extend(items)

    def destinations(self) -> list[str]:
        return [frame["destination"] for frame in self.sent]


class FakeStreamTransport:
    """Hands out scripted connections or connect errors in order; the last entry repeats."""

    def __init__(
        self, clock: FakeClock, connections: Sequence[FakeConnection | TransportError]
    ) -> None:
        self._clock = clock
        self._connections = list(connections)
        self.urls: list[str] = []

    def connect(self, url: str) -> Result[StreamConnection, TransportError]:
        self.urls.append(url)
        item = self._connections.pop(0) if len(self._connections) > 1 else self._connections[0]
        if isinstance(item, TransportError):
            return Err(item)
        item.clock = self._clock
        return Ok(item)


def ack_frame(
    correlation_id: str,
    subscriptions: dict[str, str] | None = None,
    *,
    status: str = "OK",
    error_code: str | None = None,
) -> str:
    payload: dict[str, Any] = {} if subscriptions is None else {"subscriptions": subscriptions}
    if error_code is not None:
        payload["errorCode"] = error_code
    return json.dumps({"status": status, "correlationId": correlation_id, "payload": payload})


def quote_frame(epic: str = "BTCUSD", bid: str = "1.5", timestamp: int = 1794446435768) -> str:
    payload = {"epic": epic, "bid": bid, "bidQty": 1, "ofr": "1.6", "ofrQty": 1}
    return json.dumps(
        {"status": "OK", "destination": "quote", "payload": {**payload, "timestamp": timestamp}}
    )


def auto_ack(frame: dict[str, Any]) -> list[str]:
    """Answer every request as the server does when it accepts all of it."""
    payload = frame.get("payload") or {}
    epics = payload.get("epics", [])
    if frame["destination"].startswith("OHLC"):
        resolutions = payload.get("resolutions", ["MINUTE"])
        kind = payload.get("type", "classic")
        keys = [f"{e}:{r}:{kind}" for e in epics for r in resolutions]
    else:
        keys = list(epics)
    subscriptions = None if frame["destination"] == "ping" else dict.fromkeys(keys, "PROCESSED")
    return [ack_frame(frame["correlationId"], subscriptions)]
