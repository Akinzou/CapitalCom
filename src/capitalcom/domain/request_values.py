"""Rules for caller values that end up in a URL, checked before anything is sent."""

from collections.abc import Iterable
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


def comma_list(values: Iterable[str], field: str, *, max_items: int | None) -> str:
    """Join ids for a comma-separated query parameter, de-duplicated in order.

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
    return ",".join(items)
