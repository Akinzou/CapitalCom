"""Sends a request with throttling and the retries that are safe for its method."""

import random
from collections.abc import Callable

from capitalcom.application.error_mapping import error_for
from capitalcom.application.logs import get_logger
from capitalcom.application.ports import Clock, HttpRequest, HttpResponse, HttpTransport
from capitalcom.application.rate_limiter import RateLimiter
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import RetryPolicy, backoff_delay, is_idempotent
from capitalcom.domain.errors import CapitalComError, OutcomeUnknownError, RateLimitError

_log = get_logger(__name__)

# Statuses a gateway returns when the backend never answered. Retried only for GET: on a POST
# the backend may already have booked the trade before the gateway gave up.
_GATEWAY_STATUSES = frozenset({502, 503, 504})


class Dispatcher:
    """Owns the decision whether a failed attempt is repeated, reported or made unknown."""

    def __init__(
        self,
        transport: HttpTransport,
        clock: Clock,
        limiter: RateLimiter,
        policy: RetryPolicy,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._limiter = limiter
        self._policy = policy
        self._rand = rand

    def send(self, request: HttpRequest) -> Result[HttpResponse, CapitalComError]:
        """Send ``request``; ``Ok`` only for a 2xx response."""
        idempotent = is_idempotent(request.method)
        last: Err[CapitalComError] = Err(CapitalComError("no attempt was made"))
        for attempt in range(self._policy.max_attempts):
            self._limiter.acquire(request.method, request.path)
            outcome = self._attempt(request, idempotent)
            if not isinstance(outcome, tuple):
                return outcome
            last, retry_after = outcome
            if attempt + 1 < self._policy.max_attempts:
                delay = backoff_delay(self._policy, attempt, retry_after, self._rand)
                _log.info(
                    "retrying %s %s in %.2fs: %s", request.method, request.path, delay, last.error
                )
                self._clock.sleep(delay)
        return last

    def _attempt(
        self, request: HttpRequest, idempotent: bool
    ) -> Result[HttpResponse, CapitalComError] | tuple[Err[CapitalComError], float | None]:
        """Return a final result, or ``(error, retry_after)`` when the attempt may be repeated."""
        sent = self._transport.send(request)
        if isinstance(sent, Err):
            if idempotent:
                return Err[CapitalComError](sent.error), None
            if sent.error.reached_server:
                return Err(OutcomeUnknownError(request.method, request.path))
            return Err(sent.error)
        response = sent.value
        if 200 <= response.status < 300:
            return Ok(response)
        error = error_for(response, self._clock.now_utc())
        if isinstance(error, RateLimitError):
            # The server refused before acting, so even a trade is safe to resend.
            return Err[CapitalComError](error), error.retry_after
        if response.status >= 500 and not idempotent:
            return Err(OutcomeUnknownError(request.method, request.path))
        if response.status in _GATEWAY_STATUSES:
            return Err[CapitalComError](error), None
        return Err(error)
