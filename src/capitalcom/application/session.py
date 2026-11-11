"""Session lifecycle: lazy login, renewal before the idle timeout, and logout."""

import threading
from dataclasses import dataclass, field

from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.logs import forget_secret, get_logger, register_secret
from capitalcom.application.ports import Clock, HttpRequest
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import SESSION_PATH
from capitalcom.domain.errors import (
    AuthenticationError,
    CapitalComError,
    ResponseFormatError,
)
from capitalcom.domain.secret import Secret

_log = get_logger(__name__)

# Capital.com expires a session 10 minutes after its last use. Renewing 30 s early covers
# clock drift and the time a slow request spends in flight.
IDLE_TIMEOUT_S = 600.0
RENEW_MARGIN_S = 30.0


@dataclass(frozen=True, slots=True)
class Credentials:
    """Login data. The identifier is an e-mail address, so it is kept out of the repr too."""

    api_key: Secret
    identifier: str = field(repr=False)
    password: Secret


@dataclass(frozen=True, slots=True)
class SessionTokens:
    """Tokens of one login. ``generation`` tells a stale copy from the current one."""

    cst: Secret
    security_token: Secret
    generation: int

    def headers(self) -> dict[str, str]:
        """Headers that authenticate a request with this session."""
        return {"CST": self.cst.reveal(), "X-SECURITY-TOKEN": self.security_token.reveal()}


class SessionManager:
    """Hands out valid tokens; at most one login is in flight at any time."""

    def __init__(self, dispatcher: Dispatcher, clock: Clock, credentials: Credentials) -> None:
        self._dispatcher = dispatcher
        self._clock = clock
        self._credentials = credentials
        # One lock for check-and-login: eight threads finding an expired session must produce
        # one login, not eight that each rotate the tokens of the others.
        self._lock = threading.Lock()
        self._tokens: SessionTokens | None = None
        self._last_used = 0.0
        self._generation = 0
        self._closed = False
        register_secret(credentials.api_key.reveal())
        register_secret(credentials.password.reveal())

    def tokens(self) -> Result[SessionTokens, CapitalComError]:
        """Return current tokens, logging in first when there are none or they are near expiry."""
        with self._lock:
            if self._closed:
                return Err(CapitalComError("client is closed; create a new one"))
            now = self._clock.monotonic()
            if self._tokens is not None and now - self._last_used < IDLE_TIMEOUT_S - RENEW_MARGIN_S:
                return Ok(self._tokens)
            self._drop()
            return self._login()

    def mark_used(self) -> None:
        """Record that the session served a request, which restarts the server's idle timer."""
        with self._lock:
            self._last_used = self._clock.monotonic()

    def invalidate(self, stale: SessionTokens) -> None:
        """Forget ``stale`` after a 401, unless another thread has already replaced it."""
        with self._lock:
            if self._tokens is not None and self._tokens.generation == stale.generation:
                self._drop()

    def logout(self) -> Result[None, CapitalComError]:
        """End the session on the server; a no-op when there is none or it already expired."""
        with self._lock:
            tokens = self._tokens
            if tokens is None:
                return Ok(None)
            idle = self._clock.monotonic() - self._last_used
            # Forgotten locally whatever the server says: the tokens die server-side within
            # ten minutes anyway, and keeping them would let a failed logout be reused.
            self._drop()
            if idle >= IDLE_TIMEOUT_S - RENEW_MARGIN_S:
                # The server has dropped (or is about to drop) the session and would answer
                # 401; there is nothing left to end.
                return Ok(None)
            result = self._dispatcher.send(HttpRequest("DELETE", SESSION_PATH, tokens.headers()))
        # 401 means the session is already gone, which is what logout wanted.
        if isinstance(result, Err) and not isinstance(result.error, AuthenticationError):
            return result
        _log.info("logged out")
        return Ok(None)

    def close(self) -> Result[None, CapitalComError]:
        """Log out and refuse any later login, so a closed client cannot leak a new session."""
        with self._lock:
            self._closed = True
        return self.logout()

    def _drop(self) -> None:
        if self._tokens is not None:
            forget_secret(self._tokens.cst.reveal())
            forget_secret(self._tokens.security_token.reveal())
            self._tokens = None

    def _login(self) -> Result[SessionTokens, CapitalComError]:
        request = HttpRequest(
            "POST",
            SESSION_PATH,
            headers={"X-CAP-API-KEY": self._credentials.api_key.reveal()},
            json={
                "identifier": self._credentials.identifier,
                "password": self._credentials.password.reveal(),
                "encryptedPassword": False,
            },
        )
        sent = self._dispatcher.send(request)
        if isinstance(sent, Err):
            return sent
        response = sent.value
        cst = response.header("CST")
        security_token = response.header("X-SECURITY-TOKEN")
        if not cst or not security_token:
            missing = "CST" if not cst else "X-SECURITY-TOKEN"
            return Err(
                ResponseFormatError(response.status, None, f"login response lacks {missing}")
            )
        register_secret(cst)
        register_secret(security_token)
        self._generation += 1
        self._tokens = SessionTokens(Secret(cst), Secret(security_token), self._generation)
        self._last_used = self._clock.monotonic()
        _log.info("logged in (session generation %d)", self._generation)
        return Ok(self._tokens)
