"""In-memory test doubles for the application ports. They never touch the network or sleep."""

import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from capitalcom.application.ports import HttpRequest, HttpResponse
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
