"""Raw 1.0.4 shapes for ``CapitalClient``'s account calls."""

from decimal import Decimal
from typing import Any


def as_floats(value: Any) -> Any:  # noqa: ANN401 - walks arbitrary JSON
    """``value`` with every ``Decimal`` turned into ``float``, as 1.0.4's ``json()`` gave it.

    The core decodes JSON numbers as ``Decimal``; ``float(Decimal)`` rounds to the nearest
    float, which is the float ``json.loads`` makes from the same text, so values stay equal.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: as_floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [as_floats(item) for item in value]
    return value
