"""Waits for the final confirmation of a submitted deal."""

from collections.abc import Mapping

from capitalcom.application.api_client import ApiClient
from capitalcom.application.json_codec import path_segment
from capitalcom.application.ports import Clock
from capitalcom.application.result import Err, Ok, Result
from capitalcom.domain.confirmation import DealConfirmation, Outcome
from capitalcom.domain.errors import (
    ApiError,
    CapitalComError,
    ConfirmationTimeoutError,
    DealRejectedError,
    NotFoundError,
    OutcomeUnknownError,
    ResponseFormatError,
)
from capitalcom.domain.parsing import format_error

# 1.0.4 users saw this code while the confirmation was not yet booked; it means "ask again",
# not "your reference is wrong", for the first few hundred milliseconds after a trade.
_NOT_READY_CODE = "error.invalid.dealReference"


def _not_ready(error: CapitalComError) -> bool:
    if isinstance(error, NotFoundError):
        return True
    return (
        isinstance(error, ApiError) and error.status == 400 and error.error_code == _NOT_READY_CODE
    )


def _unknown(path: str, cause: CapitalComError) -> Err[CapitalComError]:
    """The deal was submitted but polling failed, so its outcome is unknown.

    Returning the raw cause would be wrong: a connect-timeout TransportError means "never
    sent" for the poll, and a caller could read it as permission to resend the trade.
    """
    error = OutcomeUnknownError("GET", path)
    error.__cause__ = cause
    return Err(error)


class DealConfirmer:
    """Polls ``/confirms/{dealReference}`` until the deal is accepted, rejected or overdue."""

    def __init__(
        self, api: ApiClient, clock: Clock, timeout_s: float = 5.0, interval_s: float = 0.1
    ) -> None:
        self._api = api
        self._clock = clock
        self._timeout_s = timeout_s
        self._interval_s = interval_s

    def confirm(self, deal_reference: str) -> Result[DealConfirmation, CapitalComError]:
        """Return the accepted confirmation, or why there is none.

        Polling always asks at least once, so a zero timeout means "check now" rather than
        "fail without looking".
        """
        deadline = self._clock.monotonic() + self._timeout_s
        while True:
            outcome = self.poll(deal_reference)
            if outcome is not None:
                return outcome
            if self._clock.monotonic() + self._interval_s > deadline:
                return Err(ConfirmationTimeoutError(deal_reference))
            self._clock.sleep(self._interval_s)

    def poll(self, deal_reference: str) -> Result[DealConfirmation, CapitalComError] | None:
        """Ask once; return the final result, or ``None`` while the deal is still pending."""
        path = f"/api/v1/confirms/{path_segment(deal_reference)}"
        called = self._api.call("GET", path)
        if isinstance(called, Err):
            return None if _not_ready(called.error) else _unknown(path, called.error)
        if not isinstance(called.value, Mapping):
            return _unknown(path, format_error("confirms", "expected a JSON object"))
        try:
            confirmation = DealConfirmation.from_api(called.value)
            outcome = confirmation.outcome
        except ResponseFormatError as error:
            return _unknown(path, error)
        if outcome is Outcome.ACCEPTED:
            return Ok(confirmation)
        if outcome is Outcome.REJECTED:
            return Err(DealRejectedError(deal_reference, confirmation.reason))
        return None
