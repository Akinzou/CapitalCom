"""Trading helpers of ``CapitalClient``: the 1.0.4 request body and dealIds from confirmations."""

from decimal import Decimal
from typing import Any

from capitalcom.api.composition import Core
from capitalcom.application.logs import get_logger
from capitalcom.application.result import Err
from capitalcom.domain.confirmation import DealConfirmation
from capitalcom.domain.errors import (
    CapitalComError,
    ConfirmationTimeoutError,
    OutcomeUnknownError,
)

_log = get_logger(__name__)


def open_body(
    epic: str,
    size: float,
    direction: str,
    stop_dist: float | None,
    profit_dist: float | None,
) -> dict[str, Any]:
    """The body 1.0.4 posted, floats included.

    Kept byte for byte rather than built as an ``OrderRequest``: that type refuses floats
    such as ``0.001 * 100000``, and dropping ``forceOpen``, ``orderType`` or ``expiry`` would
    change a request whose effect on the server was never observed.
    """
    body: dict[str, Any] = {
        "epic": epic,
        "expiry": "-",
        "direction": direction,
        "size": size,
        "orderType": "MARKET",
        "guaranteedStop": False,
        "forceOpen": True,
    }
    # Truthiness, not "is not None": 1.0.4 ignored a zero distance, and callers rely on it.
    if stop_dist:
        body["stopDistance"] = stop_dist
    if profit_dist:
        body["profitDistance"] = profit_dist
    return body


def affected_deal_id(confirmation: DealConfirmation) -> str:
    """The first affected deal's id, whatever its status, as 1.0.4 returned it.

    A deal that affected nothing (an opposite open netting against a position, ADR 0010)
    raises: there is no id to return, and a guessed one would be closed by mistake later.
    """
    if confirmation.affected_deals:
        return confirmation.affected_deals[0].deal_id
    raise CapitalComError(
        f"deal {confirmation.deal_reference} was accepted but opened no position "
        "(it netted against an open one)"
    )


def resolve_deal_id(core: Core, deal_reference: str, retries: int, delay: float) -> str:
    """Poll ``/confirms`` at most ``retries`` times, ``delay`` seconds apart."""
    for attempt in range(retries):
        polled = core.confirmer.poll(deal_reference)
        if isinstance(polled, Err) and isinstance(polled.error, OutcomeUnknownError):
            # The poller says "outcome unknown" because it assumes a trade was just sent;
            # here it is a plain lookup, so the real failure (often a network error) is
            # raised instead of a message telling the caller to check their positions.
            cause = polled.error.__cause__
            raise cause if isinstance(cause, CapitalComError) else polled.error
        if polled is not None:
            return affected_deal_id(polled.unwrap())
        if attempt + 1 < retries:
            core.clock.sleep(delay)
    raise ConfirmationTimeoutError(deal_reference)


def warn_if_resized(requested: object, confirmation: DealConfirmation) -> None:
    """Log when the server booked another size than requested.

    A warning, not ``SizeAdjustedError``: the deal exists, and 1.0.4 code expects the dealId
    back. Non-numeric sizes are left to the server, which refused them in 1.0.4 too.
    """
    booked = confirmation.size
    if booked is None or isinstance(requested, bool):
        return
    if not isinstance(requested, int | float | Decimal):
        return
    if booked != Decimal(str(requested)):
        _log.warning(
            "deal %s booked size %s instead of the requested %s",
            confirmation.deal_reference,
            booked,
            requested,
        )
