"""Rules for caller values sent in a request, checked before anything is sent."""

from collections.abc import Iterable
from decimal import Decimal
from urllib.parse import quote

from capitalcom.domain.errors import ValidationError

# "." and ".." are refused, not encoded: quote() leaves them as they are, and URL
# normalisation would collapse them into a parent path, so remove_market("..", "session")
# would reach DELETE /api/v1/session.
_DOT_SEGMENTS = frozenset({".", ".."})


def path_segment(value: object, field: str) -> str:
    """Return ``value`` percent-encoded for use as one URL path segment."""
    if not isinstance(value, str) or not value.strip() or value in _DOT_SEGMENTS:
        raise ValidationError(f"{field} must be a non-empty string other than '.' or '..'")
    return quote(value, safe="")


def comma_list(values: Iterable[str], field: str, *, max_items: int | None) -> tuple[str, ...]:
    """Ids for a comma-separated query parameter, de-duplicated in order; callers join them.

    A bare string is refused because iterating it would send one id per character. An empty
    list is refused because the server answers an empty parameter with a 400 or a 500.
    """
    if isinstance(values, str):
        raise ValidationError(f"{field} must be an iterable of strings, not a string")
    given = list(values)
    # Checked before de-duplication, which hashes the items: a list item would otherwise
    # escape as a TypeError instead of a ValidationError.
    for item in given:
        if not isinstance(item, str) or not item.strip() or "," in item:
            raise ValidationError(f"{field}: each item must be a non-blank string without ','")
    items = list(dict.fromkeys(given))
    if not items:
        raise ValidationError(f"{field} must not be empty")
    if max_items is not None and len(items) > max_items:
        raise ValidationError(f"{field}: at most {max_items} items, got {len(items)}")
    return tuple(items)


def caller_quantity(value: object, field: str) -> Decimal:
    """Return a caller-given amount as ``Decimal``; bools, floats and non-finite values raise.

    A float is refused because it may already carry a binary rounding error, and a bool
    because it is an int that is never meant as a quantity.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        raise ValidationError(f"{field} must be a Decimal or int, got {value!r}")
    result = Decimal(value)
    if not result.is_finite():
        raise ValidationError(f"{field} must be finite, got {value!r}")
    return result


def bounded_int(value: object, field: str, low: int, high: int) -> int:
    """Return ``value`` when it is an int within ``low..high``; a bool is refused."""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValidationError(f"{field} must be an int within {low}..{high}, got {value!r}")
    return value
