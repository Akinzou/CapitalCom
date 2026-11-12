"""Session lifecycle: lazy login, renewal before the idle timeout, and logout."""

import threading
from dataclasses import dataclass, field

from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.login import (
    PasswordEncryptor,
    encrypt_for_login,
    encryption_key_request,
    is_already_active,
    login_request,
    parse_login,
    switch_request,
)
from capitalcom.application.logs import forget_secret, get_logger, register_secret
from capitalcom.application.ports import Clock, HttpRequest, HttpResponse
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import SESSION_PATH
from capitalcom.domain.errors import AuthenticationError, CapitalComError, ValidationError
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

    def __init__(
        self,
        dispatcher: Dispatcher,
        clock: Clock,
        credentials: Credentials,
        encryptor: PasswordEncryptor | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._clock = clock
        self._credentials = credentials
        self._encryptor = encryptor
        # One lock for check-and-login: eight threads finding an expired session must produce
        # one login, not eight that each rotate the tokens of the others.
        self._lock = threading.Lock()
        self._tokens: SessionTokens | None = None
        self._last_used = 0.0
        self._generation = 0
        self._closed = False
        # The account the session is on, and the one the caller chose. They differ only
        # between a fresh login (which lands on the default account) and the re-applied
        # switch; a token is never handed out while they differ.
        self._current_account: str | None = None
        self._selected_account: str | None = None
        register_secret(credentials.api_key.reveal())
        register_secret(credentials.password.reveal())

    def tokens(self) -> Result[SessionTokens, CapitalComError]:
        """Return current tokens, logging in first when there are none or they are near expiry."""
        with self._lock:
            return self._valid_tokens(self._selected_account)

    @property
    def current_account_id(self) -> str | None:
        """Account the live session is on; ``None`` before the first login."""
        with self._lock:
            return self._current_account

    def switch_account(self, account_id: str) -> Result[None, CapitalComError]:
        """Move the session to ``account_id`` and keep it there across later re-logins."""
        if not account_id:
            return Err(ValidationError("account_id must be a non-empty string"))
        with self._lock:
            # Without a live session the login goes straight to ``account_id``: re-applying
            # the old selection first would cost a request and, if that account can no
            # longer be selected, would make it impossible to switch away from it.
            tokens = self._valid_tokens(account_id)
            if isinstance(tokens, Err):
                return tokens
            if self._current_account == account_id:
                self._selected_account = account_id
                return Ok(None)
            switched = self._switch(tokens.value, account_id)
            if isinstance(switched, Err) and isinstance(switched.error, AuthenticationError):
                # The session died between the token check and the PUT; a login that targets
                # the account directly does the switch as part of getting the new tokens.
                self._drop()
                switched = self._login(account_id)
            return switched if isinstance(switched, Err) else Ok(None)

    def current_tokens(self) -> SessionTokens | None:
        """The live tokens, or ``None`` when there is no session; never logs in."""
        with self._lock:
            return self._tokens

    def adopt_tokens(self, cst: str | None, security_token: str | None) -> None:
        """Use a token pair obtained elsewhere; an empty or ``None`` half drops the session.

        The account of adopted tokens is unknown, so ``current_account_id`` becomes ``None``
        and the account chosen earlier is forgotten: re-applying it on the next renewal
        would move a session its owner never pointed at that account.
        """
        with self._lock:
            self._drop()
            self._selected_account = None
            if cst and security_token:
                self._adopt(cst, security_token)

    def idle_remaining_s(self) -> float | None:
        """Seconds until the server's idle timeout ends the session; ``None`` without one."""
        with self._lock:
            if self._tokens is None:
                return None
            return IDLE_TIMEOUT_S - (self._clock.monotonic() - self._last_used)

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
        self._current_account = None

    def _valid_tokens(self, target: str | None) -> Result[SessionTokens, CapitalComError]:
        if self._closed:
            return Err(CapitalComError("client is closed; create a new one"))
        now = self._clock.monotonic()
        if self._tokens is not None and now - self._last_used < IDLE_TIMEOUT_S - RENEW_MARGIN_S:
            return Ok(self._tokens)
        self._drop()
        return self._login(target)

    def _login(self, target: str | None) -> Result[SessionTokens, CapitalComError]:
        sent = self._send_login()
        if isinstance(sent, Err):
            return sent
        grant = parse_login(sent.value)
        if isinstance(grant, Err):
            return grant
        tokens = self._adopt(grant.value.cst, grant.value.security_token)
        self._current_account = grant.value.account_id
        _log.info("logged in (session generation %d)", self._generation)
        if target is None:
            return Ok(tokens)
        if target == self._current_account:
            self._selected_account = target
            return Ok(tokens)
        # Also reached when the login did not name its account: the PUT then settles it, and
        # an "already active" answer counts as success.
        switched = self._switch(tokens, target)
        if isinstance(switched, Err):
            # A token for the default account must not reach a caller who chose another one:
            # an order placed with it would land on the wrong account. The session is ended
            # too, so repeated failures do not pile up sessions against the server's limit.
            self._end(tokens)
            self._drop()
        return switched

    def _send_login(self) -> Result[HttpResponse, CapitalComError]:
        api_key = self._credentials.api_key.reveal()
        password = self._credentials.password.reveal()
        identifier = self._credentials.identifier
        if self._encryptor is None:
            return self._dispatcher.send(
                login_request(api_key, identifier, password, encrypted=False)
            )
        # A fresh key for every login, renewals included: the ciphertext embeds the server's
        # timestamp, and a reused one may be refused as stale.
        sent = self._dispatcher.send(encryption_key_request(api_key))
        if isinstance(sent, Err):
            return sent
        encrypted = encrypt_for_login(sent.value, password, self._encryptor)
        if isinstance(encrypted, Err):
            return encrypted
        # Masked only while the request can be logged: every login makes a new ciphertext, and
        # keeping each one would grow the redaction registry for as long as the bot runs.
        register_secret(encrypted.value)
        try:
            return self._dispatcher.send(
                login_request(api_key, identifier, encrypted.value, encrypted=True)
            )
        finally:
            forget_secret(encrypted.value)

    def _end(self, tokens: SessionTokens) -> None:
        ended = self._dispatcher.send(HttpRequest("DELETE", SESSION_PATH, tokens.headers()))
        if isinstance(ended, Err):
            _log.warning("could not end the session after a failed switch: %s", ended.error)

    def _switch(
        self, tokens: SessionTokens, account_id: str
    ) -> Result[SessionTokens, CapitalComError]:
        # Sent through the dispatcher, not ApiClient, because the answer may carry new
        # session tokens in its headers and ApiClient keeps only the body.
        sent = self._dispatcher.send(switch_request(tokens.headers(), account_id))
        if isinstance(sent, Err):
            if not is_already_active(sent.error):
                return sent
        else:
            cst = sent.value.header("CST")
            security_token = sent.value.header("X-SECURITY-TOKEN")
            if cst and security_token:
                self._drop()
                tokens = self._adopt(cst, security_token)
        self._current_account = self._selected_account = account_id
        self._last_used = self._clock.monotonic()
        _log.info("switched account")
        return Ok(tokens)

    def _adopt(self, cst: str, security_token: str) -> SessionTokens:
        register_secret(cst)
        register_secret(security_token)
        self._generation += 1
        self._tokens = SessionTokens(Secret(cst), Secret(security_token), self._generation)
        self._last_used = self._clock.monotonic()
        return self._tokens
