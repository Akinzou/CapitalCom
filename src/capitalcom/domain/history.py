"""Account history: activity and transactions, and the time window they are queried by."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from capitalcom.domain.api_time import window_params
from capitalcom.domain.errors import ValidationError
from capitalcom.domain.parsing import optional_str, require_decimal, require_str, require_utc


@dataclass(frozen=True, slots=True)
class Activity:
    """One account event, from ``GET /api/v1/history/activity``.

    ``type``, ``status`` and ``source`` stay strings so that a value Capital.com adds later
    does not break a history listing. ``date`` is read from ``dateUTC``; the local ``date``
    field stays in ``raw``.
    """

    date: datetime
    deal_id: str
    type: str
    status: str
    epic: str | None = None
    source: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Activity":
        """Build an activity from its JSON object."""
        return cls(
            date=require_utc(payload, "dateUTC"),
            deal_id=require_str(payload, "dealId"),
            type=require_str(payload, "type"),
            status=require_str(payload, "status"),
            epic=optional_str(payload, "epic"),
            source=optional_str(payload, "source"),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class Transaction:
    """One money movement, from ``GET /api/v1/history/transactions``.

    ``date`` is read from ``dateUtc``, spelled so by this endpoint (activity uses
    ``dateUTC``). ``size`` arrives as a string and becomes a ``Decimal``.
    """

    date: datetime
    transaction_type: str
    reference: str
    size: Decimal
    currency: str
    instrument_name: str | None = None
    note: str | None = None
    status: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Transaction":
        """Build a transaction from its JSON object."""
        return cls(
            date=require_utc(payload, "dateUtc"),
            transaction_type=require_str(payload, "transactionType"),
            reference=require_str(payload, "reference"),
            size=require_decimal(payload, "size"),
            currency=require_str(payload, "currency"),
            instrument_name=optional_str(payload, "instrumentName"),
            note=optional_str(payload, "note"),
            status=optional_str(payload, "status"),
            raw=payload,
        )


def history_params(
    start: datetime | None,
    end: datetime | None,
    last_period: timedelta | None,
    *,
    max_span: timedelta | None,
) -> dict[str, str]:
    """Query parameters for a history window, validated before anything is sent.

    The server answers an invalid window with a generic 400, or silently narrows it, so each
    rule it documents is checked here with a message that names the problem.
    """
    if last_period is not None:
        if start is not None or end is not None:
            raise ValidationError("last_period cannot be combined with start or end")
        return {"lastPeriod": str(_whole_seconds(last_period, max_span))}
    params = window_params(start, end)
    if start is not None and end is not None and max_span is not None and end - start > max_span:
        raise ValidationError(f"the range from start to end must not exceed {max_span}")
    return params


def _whole_seconds(period: timedelta, max_span: timedelta | None) -> int:
    # The API takes whole seconds; a fractional period is refused rather than rounded, so the
    # window sent is always the one asked for.
    if period < timedelta(seconds=1) or period % timedelta(seconds=1):
        raise ValidationError(f"last_period must be a whole number of seconds >= 1, got {period}")
    if max_span is not None and period > max_span:
        raise ValidationError(f"last_period must not exceed {max_span}, got {period}")
    return int(period.total_seconds())
