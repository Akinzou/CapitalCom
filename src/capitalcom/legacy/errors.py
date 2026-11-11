"""Network errors of ``CapitalClient`` that 1.x ``except requests...`` clauses still catch."""

import requests

from capitalcom.application.ports import HttpRequest, HttpResponse, HttpTransport
from capitalcom.application.result import Err, Result
from capitalcom.domain.errors import TransportError


class LegacyTransportError(TransportError, requests.exceptions.ConnectionError):
    """A ``TransportError`` that is also a ``requests.exceptions.ConnectionError``.

    In 1.0.4 a network failure surfaced as a ``requests`` exception, and bots retry on
    ``except requests.exceptions.ConnectionError`` (or ``RequestException``). A plain
    ``TransportError`` would slip past those clauses and stop the bot on the first blip.
    """


class LegacyTransport:
    """Wraps the real transport so every network failure is a ``LegacyTransportError``.

    Mapped once, at the bottom of the stack, rather than per legacy method: a method added
    later cannot forget it. ``OutcomeUnknownError`` is made above this layer and is not a
    ``TransportError``, so a retry-on-network-error clause cannot resend a trade.
    """

    def __init__(self, inner: HttpTransport) -> None:
        self._inner = inner

    def send(self, request: HttpRequest) -> Result[HttpResponse, TransportError]:
        """Send through the wrapped transport, re-typing a network failure."""
        sent = self._inner.send(request)
        if isinstance(sent, Err) and not isinstance(sent.error, LegacyTransportError):
            error = LegacyTransportError(str(sent.error), sent.error.reached_server)
            error.__cause__ = sent.error
            return Err(error)
        return sent
