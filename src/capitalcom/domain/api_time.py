"""Formatting of caller-supplied datetimes for Capital.com query parameters."""

from datetime import UTC, datetime

from capitalcom.domain.errors import ValidationError

# The API takes local-looking timestamps without an offset and filters on its UTC fields, so
# every value is converted to UTC first. A naive datetime is refused rather than guessed: the
# machine's local zone and UTC differ by hours, which would silently shift the range.
_API_FORMAT = "%Y-%m-%dT%H:%M:%S"


def to_api_time(value: datetime, field: str) -> str:
    """Return ``value`` in UTC as ``YYYY-MM-DDTHH:MM:SS``; a naive value raises."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{field}: datetime must be timezone-aware")
    return value.astimezone(UTC).strftime(_API_FORMAT)


def window_params(start: datetime | None, end: datetime | None) -> dict[str, str]:
    """``from``/``to`` query parameters for the bounds given; a start after the end raises."""
    params: dict[str, str] = {}
    if start is not None:
        params["from"] = to_api_time(start, "start")
    if end is not None:
        params["to"] = to_api_time(end, "end")
    if start is not None and end is not None and start > end:
        raise ValidationError(f"start {start} is after end {end}")
    return params
