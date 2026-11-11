"""Public error hierarchy.

Every error derives from ``CapitalComError`` and therefore from ``Exception``, so code written
for 1.x with ``except Exception`` keeps working. Errors that come from a server response derive
from ``ApiError`` and carry the HTTP status and Capital.com's ``errorCode`` (ADR 0005).
"""

from typing import Any

BODY_LIMIT = 500


class CapitalComError(Exception):
    """Root of every error raised by this library."""

    def __init__(self, message: str, *init_args: object) -> None:
        super().__init__(message)
        # Kept so pickling rebuilds the error from its constructor arguments rather than from
        # the formatted message, which the subclasses' signatures would reject.
        self._init_args: tuple[object, ...] = init_args or (message,)

    def __reduce__(self) -> tuple[Any, tuple[Any, ...]]:
        return type(self), self._init_args


class ValidationError(CapitalComError):
    """A request broke a rule that is checked locally, before anything was sent."""


class ApiError(CapitalComError):
    """The server answered with an error status.

    ``body`` is cut to 500 characters: a proxy error page can be megabytes long and would
    otherwise flood logs and tracebacks.
    """

    def __init__(self, status: int, error_code: str | None, body: str) -> None:
        self._status = status
        self._error_code = error_code
        self._body = body[:BODY_LIMIT]
        super().__init__(
            f"HTTP {status} {error_code or '(no error code)'}: {self._body}",
            status,
            error_code,
            self._body,
        )

    @property
    def status(self) -> int:
        """HTTP status code of the response."""
        return self._status

    @property
    def error_code(self) -> str | None:
        """Capital.com ``errorCode`` from a JSON body, or ``None`` when there was none."""
        return self._error_code

    @property
    def body(self) -> str:
        """Response body, truncated to 500 characters."""
        return self._body


class AuthenticationError(ApiError):
    """The credentials or the session were rejected (HTTP 401)."""


class NotFoundError(ApiError):
    """The requested resource does not exist (HTTP 404)."""


class RateLimitError(ApiError):
    """The server kept refusing requests with HTTP 429 after every allowed retry."""

    def __init__(
        self, status: int, error_code: str | None, body: str, retry_after: float | None = None
    ) -> None:
        super().__init__(status, error_code, body)
        self._retry_after = retry_after
        self._init_args = (status, error_code, self.body, retry_after)

    @property
    def retry_after(self) -> float | None:
        """Seconds the server asked to wait, when it sent ``Retry-After``."""
        return self._retry_after


class ResponseFormatError(ApiError):
    """A response, often a successful one, did not have the documented shape."""


class TransportError(CapitalComError):
    """The request failed below HTTP: DNS, TLS, connection reset or timeout."""

    def __init__(self, message: str, reached_server: bool = True) -> None:
        super().__init__(message, message, reached_server)
        self._reached_server = reached_server

    @property
    def reached_server(self) -> bool:
        """False only when the request provably never left this machine (e.g. connect error)."""
        return self._reached_server


class OutcomeUnknownError(CapitalComError):
    """A non-idempotent request may or may not have been executed by the server.

    Raised instead of retrying, because retrying a trade that did go through opens a second
    position.
    """

    def __init__(self, method: str, path: str) -> None:
        super().__init__(
            f"{method} {path}: outcome unknown, the server may have executed it. "
            "Check open positions and orders before retrying.",
            method,
            path,
        )
        self._method = method
        self._path = path

    @property
    def method(self) -> str:
        """HTTP method of the request whose outcome is unknown."""
        return self._method

    @property
    def path(self) -> str:
        """Path of the request whose outcome is unknown."""
        return self._path


class DealRejectedError(CapitalComError):
    """Capital.com confirmed the deal as rejected."""

    def __init__(self, deal_reference: str, reason: str | None) -> None:
        super().__init__(
            f"Deal {deal_reference} rejected: {reason or '(no reason given)'}",
            deal_reference,
            reason,
        )
        self._deal_reference = deal_reference
        self._reason = reason

    @property
    def deal_reference(self) -> str:
        """Reference returned when the deal was submitted."""
        return self._deal_reference

    @property
    def reason(self) -> str | None:
        """Rejection reason reported by the server, if any."""
        return self._reason


class ConfirmationTimeoutError(CapitalComError):
    """No final confirmation arrived before the deadline; the deal may still execute."""

    def __init__(self, deal_reference: str) -> None:
        super().__init__(
            f"Deal {deal_reference}: no confirmation before the deadline. "
            "Check open positions and orders before retrying.",
            deal_reference,
        )
        self._deal_reference = deal_reference

    @property
    def deal_reference(self) -> str:
        """Reference returned when the deal was submitted."""
        return self._deal_reference
