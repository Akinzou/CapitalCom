"""Authenticated JSON calls on top of the dispatcher and the session manager."""

from collections.abc import Mapping
from typing import Any

from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.error_mapping import outcome_unknown
from capitalcom.application.ports import HttpRequest
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import is_retry_safe
from capitalcom.application.session import SessionManager
from capitalcom.domain.errors import (
    AuthenticationError,
    CapitalComError,
    ResponseFormatError,
)


class ApiClient:
    """Sends a request with session headers and decodes the JSON answer."""

    def __init__(self, dispatcher: Dispatcher, session: SessionManager) -> None:
        self._dispatcher = dispatcher
        self._session = session

    def call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Result[Any, CapitalComError]:
        """Return the decoded body (``None`` when empty) or the error.

        A 401 is answered by one fresh login and one resend, whatever the method: the server
        rejected the request before acting on it. A second 401 is returned, never looped on.
        """
        for attempt in range(2):
            tokens = self._session.tokens()
            if isinstance(tokens, Err):
                return tokens
            request = HttpRequest(method, path, tokens.value.headers(), params or {}, json)
            sent = self._dispatcher.send(request)
            if isinstance(sent, Err):
                if isinstance(sent.error, AuthenticationError) and attempt == 0:
                    self._session.invalidate(tokens.value)
                    continue
                return sent
            self._session.mark_used()
            if not sent.value.body.strip():
                return Ok(None)
            try:
                return Ok(sent.value.json())
            except ResponseFormatError as error:
                if is_retry_safe(method, path):
                    return Err(error)
                # A 2xx says the server took a request that changes state, as with a 5xx on
                # one; an unreadable body must not read as "nothing happened" (ADR 0006).
                return Err(outcome_unknown(method, path, error))
        raise AssertionError("unreachable: the second attempt always returns")
