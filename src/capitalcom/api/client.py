"""``CapitalCom``: the public entry point of the 2.x API."""

from types import TracebackType

import requests

from capitalcom.api.accounts import AccountsResource
from capitalcom.api.composition import Core, build_core, stream_transport
from capitalcom.api.history import HistoryResource
from capitalcom.api.markets import MarketsResource
from capitalcom.api.orders import OrdersResource
from capitalcom.api.positions import PositionsResource
from capitalcom.api.prices import PricesResource
from capitalcom.api.sentiment import SentimentResource
from capitalcom.api.session_resource import SessionResource
from capitalcom.api.stream import StreamResource
from capitalcom.api.watchlists import WatchlistsResource
from capitalcom.application.logs import get_logger
from capitalcom.application.result import Err
from capitalcom.application.retry import RetryPolicy
from capitalcom.application.session import Credentials
from capitalcom.domain.enums import Environment
from capitalcom.domain.errors import CapitalComError
from capitalcom.domain.secret import Secret

_log = get_logger(__name__)


class CapitalCom:
    """Client for the Capital.com REST and WebSocket API.

    Logs in lazily on the first call. Use it as a context manager, or call ``close()``, so the
    session is ended on the server. Errors are raised as subclasses of ``CapitalComError``.

    Args:
        api_key: API key generated in the Capital.com platform settings.
        identifier: Login (e-mail address) of the account the key belongs to.
        password: The API key's custom password.
        environment: ``Environment.DEMO`` (the default) or ``Environment.LIVE``, which trades
            real money.
        http_session: A ``requests.Session`` to send requests through, for proxies or a CA
            bundle; TLS verification cannot be switched off.
        timeout: Connect and read timeouts in seconds.
        retry: How transient failures are retried; see ``RetryPolicy``.
        confirm_timeout: Seconds to wait for a deal confirmation before
            ``ConfirmationTimeoutError``.
        encrypted_password: Send the password encrypted with the server's key (needs the
            ``encryption`` extra).
    """

    def __init__(
        self,
        api_key: str,
        identifier: str,
        password: str,
        environment: Environment = Environment.DEMO,
        *,
        http_session: requests.Session | None = None,
        timeout: tuple[float, float] = (5.0, 15.0),
        retry: RetryPolicy | None = None,
        confirm_timeout: float = 5.0,
        encrypted_password: bool = False,
    ) -> None:
        if not api_key or not identifier or not password:
            raise ValueError("api_key, identifier and password must not be empty")
        self._environment = environment
        self._core: Core = build_core(
            Credentials(Secret(api_key), identifier, Secret(password)),
            environment,
            http_session=http_session,
            timeout=timeout,
            retry=retry,
            confirm_timeout_s=confirm_timeout,
            encrypted_password=encrypted_password,
        )
        self._closed = False
        self.session = SessionResource(self._core)
        """Session details, account switching and logout."""
        self.accounts = AccountsResource(self._core)
        """Accounts, preferences and the demo top-up."""
        self.history = HistoryResource(self._core)
        """Activity and transaction history."""
        self.positions = PositionsResource(self._core)
        """Open positions: open, amend and close them."""
        self.orders = OrdersResource(self._core)
        """Working orders: create, amend and cancel them."""
        self.markets = MarketsResource(self._core)
        """Market search, navigation tree and market details."""
        self.prices = PricesResource(self._core)
        """Historical prices."""
        self.sentiment = SentimentResource(self._core)
        """Client sentiment per market."""
        self.watchlists = WatchlistsResource(self._core)
        """Watchlists and their markets."""
        self.stream = StreamResource(self._core, lambda: stream_transport(http_session))
        """Live quotes and OHLC bars over the WebSocket (``streaming`` extra)."""

    def __repr__(self) -> str:
        # The identifier is the account's e-mail address, so only the environment is shown.
        return f"CapitalCom(environment={self._environment})"

    def close(self) -> None:
        """Log out if a session exists and release connections; later calls do nothing."""
        if self._closed:
            return
        self._closed = True
        # The socket goes first: its frames carry the session tokens, and it must not outlive
        # them. A failed socket close still lets the logout run.
        try:
            self.stream.close()
        finally:
            try:
                result = self._core.session.close()
            finally:
                self._core.release()
        if isinstance(result, Err):
            result.unwrap()

    def __enter__(self) -> "CapitalCom":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.close()
            return
        # An exception is already propagating; a failed logout must not replace it, because
        # the caller needs to see why their block failed, not that cleanup failed too.
        try:
            self.close()
        except CapitalComError as error:
            _log.warning("logout after an error failed: %s", error)
