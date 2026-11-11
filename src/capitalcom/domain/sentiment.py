"""Client sentiment: the share of Capital.com clients long and short on a market."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from capitalcom.domain.parsing import require_decimal, require_str


@dataclass(frozen=True, slots=True)
class Sentiment:
    """Long and short shares of one market, in percent; ``market_id`` is the epic."""

    market_id: str
    long_percentage: Decimal
    short_percentage: Decimal
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Sentiment":
        """Build the sentiment of one market."""
        return cls(
            market_id=require_str(payload, "marketId"),
            long_percentage=require_decimal(payload, "longPositionPercentage"),
            short_percentage=require_decimal(payload, "shortPositionPercentage"),
            raw=payload,
        )
