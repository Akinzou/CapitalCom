"""JSON encoding that never silently rounds a Decimal, and decoding that never makes floats."""

import json
import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from capitalcom.domain.errors import ValidationError

# A double holds any decimal with up to 15 significant digits exactly (DBL_DIG). Capital.com
# reads request numbers as doubles, so a longer value would be rounded by the server; raising
# here beats trading a size or level the caller did not ask for (ADR 0005).
MAX_SIGNIFICANT_DIGITS = 15


def encode_json(body: Mapping[str, Any]) -> bytes:
    """Serialize a request body, writing ``Decimal`` values as JSON numbers."""
    try:
        return json.dumps(_plain(body, ""), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValidationError(f"request body is not JSON-serialisable: {error}") from None


def _plain(value: Any, path: str) -> Any:  # noqa: ANN401 - walks arbitrary JSON values
    if isinstance(value, Decimal):
        return _decimal_to_float(value, path)
    if isinstance(value, Mapping):
        return {k: _plain(v, f"{path}.{k}" if path else str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v, f"{path}[{i}]") for i, v in enumerate(value)]
    return value


def _decimal_to_float(value: Decimal, path: str) -> float:
    if not value.is_finite():
        raise ValidationError(f"{path}: {value} is not a finite number")
    if len(value.normalize().as_tuple().digits) > MAX_SIGNIFICANT_DIGITS:
        raise ValidationError(
            f"{path}: {value} has more than {MAX_SIGNIFICANT_DIGITS} significant digits "
            "and would be rounded by the server"
        )
    number = float(value)
    # Within 15 digits a double is exact only inside its normal range: 1E+400 would become
    # inf and 1E-400 would become 0.0, both sent without complaint.
    if not math.isfinite(number) or Decimal(repr(number)) != value:
        raise ValidationError(f"{path}: {value} is outside the range a double holds exactly")
    return number


def _reject_constant(name: str) -> Decimal:
    raise ValueError(f"non-standard JSON constant {name}")


def decode_json(body: bytes) -> Any:  # noqa: ANN401 - JSON is untyped until a parser reads it
    """Parse JSON with every non-integer number as ``Decimal``; raises ``ValueError``."""
    return json.loads(body, parse_float=Decimal, parse_constant=_reject_constant)


def path_segment(value: str) -> str:
    """Percent-encode a value for use as one URL path segment, including ``/``."""
    return quote(value, safe="")
