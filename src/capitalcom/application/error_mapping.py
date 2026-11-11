"""Translation of an HTTP error response into the public error hierarchy."""

from datetime import datetime

from capitalcom.application.ports import HttpResponse
from capitalcom.application.retry import parse_retry_after
from capitalcom.domain.errors import (
    ApiError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ResponseFormatError,
)

_BY_STATUS: dict[int, type[ApiError]] = {401: AuthenticationError, 404: NotFoundError}


def error_for(response: HttpResponse, now: datetime) -> ApiError:
    """Build the error for a non-2xx response.

    The body may be anything a proxy or load balancer produced, so ``errorCode`` is read only
    from a JSON object with a string value; every other body leaves it ``None`` rather than
    failing the error path itself.
    """
    text = response.body.decode("utf-8", errors="replace")
    code = _error_code(response)
    if response.status == 429:
        retry_after = parse_retry_after(response.header("Retry-After"), now)
        return RateLimitError(response.status, code, text, retry_after=retry_after)
    return _BY_STATUS.get(response.status, ApiError)(response.status, code, text)


def _error_code(response: HttpResponse) -> str | None:
    try:
        payload = response.json()
    except ResponseFormatError:
        return None
    if isinstance(payload, dict):
        code = payload.get("errorCode")
        if isinstance(code, str):
            return code
    return None
