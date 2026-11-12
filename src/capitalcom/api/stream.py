"""``cc.stream``: live quotes and OHLC bars over the Capital.com WebSocket."""

from collections.abc import Callable, Iterator, Sequence
from types import TracebackType
from typing import TypeVar

from capitalcom.api.composition import Core
from capitalcom.application.ports import StreamTransport
from capitalcom.application.result import Err, Result
from capitalcom.application.stream_session import StreamClosedError, StreamEvent, StreamSession
from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import CapitalComError, ValidationError
from capitalcom.domain.streaming import CandleType

T = TypeVar("T")


class Stream:
    """An open stream: subscribe, then iterate over ``Quote``, ``Candle`` and ``Gap`` events.

    Iteration blocks in the calling thread; the library starts no thread of its own.
    Keepalives and reconnects happen inside ``next()``. Every interruption is yielded as a
    ``Gap``; when the stream gives up it raises ``StreamError`` and iteration then stops.
    """

    def __init__(self, session: StreamSession) -> None:
        self._session = session

    @property
    def closed(self) -> bool:
        """True once the stream is closed, by ``close()`` or because it gave up."""
        return self._session.closed

    def subscribe_quotes(self, epics: Sequence[str]) -> None:
        """Receive quotes of ``epics``; at most 40 quote epics per stream."""
        _settle(self._session.subscribe_quotes(epics))

    def unsubscribe_quotes(self, epics: Sequence[str]) -> None:
        """Stop the quotes of subscribed ``epics``."""
        _settle(self._session.unsubscribe_quotes(epics))

    def subscribe_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str] = (Resolution.MINUTE,),
        candle: CandleType | str = CandleType.CLASSIC,
    ) -> None:
        """Receive bars of each epic in each resolution; at most 40 OHLC epics per stream."""
        _settle(self._session.subscribe_ohlc(epics, resolutions, candle))

    def unsubscribe_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str] | None = None,
        candles: Sequence[CandleType | str] | None = None,
    ) -> None:
        """Stop bars of ``epics``; ``None`` means every resolution or candle type."""
        _settle(self._session.unsubscribe_ohlc(epics, resolutions, candles))

    def close(self) -> None:
        """Close the socket; the server drops the subscriptions with it. Idempotent."""
        self._session.close()

    def __enter__(self) -> "Stream":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __iter__(self) -> Iterator[StreamEvent]:
        return self

    def __next__(self) -> StreamEvent:
        # A closed stream ends iteration instead of raising, so a for loop whose body closed
        # the stream, or that already saw StreamError, simply finishes.
        if self._session.closed:
            raise StopIteration
        result = self._session.next_event()
        if isinstance(result, Err) and isinstance(result.error, StreamClosedError):
            raise StopIteration  # closed meanwhile, for example by close() in another thread
        return _settle(result)


class StreamResource:
    """Opens the client's stream; one ``CapitalCom`` holds at most one open ``Stream``."""

    def __init__(self, core: Core, transport: Callable[[], StreamTransport]) -> None:
        self._core = core
        self._transport = transport
        self._open: Stream | None = None

    def connect(self) -> Stream:
        """Log in if needed and open the stream; use it as a context manager.

        Raises ``ImportError`` without the ``streaming`` extra.
        """
        if self._open is not None and not self._open.closed:
            raise ValidationError("one stream per client is already open; close it first")
        session = StreamSession(
            self._transport(),
            self._core.session,
            self._core.clock,
            self._core.environment.stream_url,
        )
        session.open().unwrap()
        self._open = Stream(session)
        return self._open

    def close(self) -> None:
        """Close the open stream, if any."""
        if self._open is not None:
            self._open.close()


def _settle(result: Result[T, CapitalComError]) -> T:
    if isinstance(result, Err):
        result.unwrap()
    return result.value
