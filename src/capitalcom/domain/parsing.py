"""Strict conversions from decoded JSON values to domain types.

Every converter names the field it was reading, so a payload change on Capital.com's side shows
up as a precise error instead of a wrong number further down.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

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


def _missing(payload: Mapping[str, Any], key: str) -> Any:  # noqa: ANN401 - untyped JSON
    value = payload.get(key)
    if value is None:
        raise format_error(key, "missing")
    return value


def require_str(payload: Mapping[str, Any], key: str) -> str:
    """Read a required string field."""
    value = _missing(payload, key)
    if not isinstance(value, str):
        raise format_error(key, f"expected a string, got {type(value).__name__}")
    return value


def optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    """Read a string field that may be absent or null."""
    return None if payload.get(key) is None else require_str(payload, key)


def require_decimal(payload: Mapping[str, Any], key: str) -> Decimal:
    """Read a required number field as ``Decimal``."""
    return to_decimal(_missing(payload, key), key)


def optional_decimal(payload: Mapping[str, Any], key: str) -> Decimal | None:
    """Read a number field that may be absent or null."""
    return None if payload.get(key) is None else require_decimal(payload, key)


def require_bool(payload: Mapping[str, Any], key: str) -> bool:
    """Read a required JSON boolean; ``0`` or ``"true"`` is a format error, not a truth value."""
    value = _missing(payload, key)
    if not isinstance(value, bool):
        raise format_error(key, f"expected a boolean, got {type(value).__name__}")
    return value


def to_int(value: object, field: str) -> int:
    """Convert a JSON integer, or a ``Decimal`` with an integral value, to ``int``."""
    # bool is an int subclass and a Decimal may carry a fraction; both would be silently
    # truncated or misread by int(), so they are rejected instead.
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise format_error(field, f"expected an integer, got {type(value).__name__}")
    if isinstance(value, Decimal) and (not value.is_finite() or value != value.to_integral()):
        raise format_error(field, f"not an integer: {value!r}")
    return int(value)


def require_int(payload: Mapping[str, Any], key: str) -> int:
    """Read a required integer field."""
    return to_int(_missing(payload, key), key)


def require_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    """Read a required JSON array."""
    value = _missing(payload, key)
    if not isinstance(value, list):
        raise format_error(key, f"expected a list, got {type(value).__name__}")
    return value


def as_mapping(value: object, field: str) -> Mapping[str, Any]:
    """Return ``value`` when it is a JSON object; a response body or a list item, say."""
    if not isinstance(value, Mapping):
        raise format_error(field, f"expected an object, got {type(value).__name__}")
    return value


def require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Read a required JSON object."""
    return as_mapping(_missing(payload, key), key)


def require_utc(payload: Mapping[str, Any], key: str) -> datetime:
    """Read a required UTC timestamp string."""
    return to_utc(require_str(payload, key), key)


def optional_utc(payload: Mapping[str, Any], key: str) -> datetime | None:
    """Read a UTC timestamp string that may be absent or null."""
    return None if payload.get(key) is None else require_utc(payload, key)


def epoch_ms_to_utc(value: object, field: str) -> datetime:
    """Convert epoch milliseconds to an aware UTC ``datetime``.

    Adding a ``timedelta`` keeps the millisecond exact; ``fromtimestamp(ms / 1000)`` goes
    through a float and can land a microsecond off.
    """
    return _EPOCH + timedelta(milliseconds=to_int(value, field))


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
