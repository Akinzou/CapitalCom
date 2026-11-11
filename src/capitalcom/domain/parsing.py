"""Strict conversions from decoded JSON values to domain types.

Every converter names the field it was reading, so a payload change on Capital.com's side shows
up as a precise error instead of a wrong number further down.
"""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from capitalcom.domain.errors import ResponseFormatError

# Parsers only ever see bodies of successful responses; a non-2xx body is turned into an
# ApiError before any payload is parsed.
_SUCCESS_STATUS = 200


def format_error(field: str, detail: str) -> ResponseFormatError:
    """Build the error for a successful response whose ``field`` has an unexpected shape."""
    return ResponseFormatError(_SUCCESS_STATUS, None, f"field {field!r}: {detail}")


def to_decimal(value: object, field: str) -> Decimal:
    """Convert a JSON number or numeric string to ``Decimal``.

    ``float`` and ``bool`` are rejected: a float means the Decimal-preserving decoder was
    bypassed and the value may already be rounded; a bool is an int subclass that is never a
    valid amount.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        raise format_error(field, f"expected a number, got {type(value).__name__}")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise format_error(field, f"not a number: {value!r}") from None
    if not result.is_finite():
        raise format_error(field, f"not a finite number: {value!r}")
    return result


def to_utc(value: str, field: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC ``datetime``.

    A value without an offset is taken as UTC. Capital.com documents its timestamps as UTC
    and sends them without an offset; the stage 1b contract test pins this assumption.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise format_error(field, f"not an ISO-8601 timestamp: {value!r}") from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
