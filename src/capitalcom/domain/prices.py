"""Historical price bars and the rules for their query parameters."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from capitalcom.domain.api_time import to_api_time
from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import ValidationError
from capitalcom.domain.parsing import require_decimal, require_mapping, require_utc

# GET /prices documents max 1..1000 (default 10); the server answers others with a 400.
MAX_BARS = 1000


@dataclass(frozen=True, slots=True)
class BidAsk:
    """One price on both sides of the book."""

    bid: Decimal
    ask: Decimal

    @classmethod
    def from_api(cls, payload: Mapping[str, Any], key: str) -> "BidAsk":
        """Read ``{"bid": ..., "ask": ...}`` stored under ``key``."""
        prices = require_mapping(payload, key)
        return cls(require_decimal(prices, "bid"), require_decimal(prices, "ask"))


@dataclass(frozen=True, slots=True)
class PriceBar:
    """One bar of ``GET /prices``; ``time`` is its UTC start, local ``snapshotTime`` is in raw."""

    time: datetime
    open: BidAsk
    close: BidAsk
    high: BidAsk
    low: BidAsk
    volume: Decimal
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "PriceBar":
        """Build a bar from one item of ``prices``."""
        return cls(
            time=require_utc(payload, "snapshotTimeUTC"),
            open=BidAsk.from_api(payload, "openPrice"),
            close=BidAsk.from_api(payload, "closePrice"),
            high=BidAsk.from_api(payload, "highPrice"),
            low=BidAsk.from_api(payload, "lowPrice"),
            volume=require_decimal(payload, "lastTradedVolume"),
            raw=payload,
        )


def price_params(
    resolution: Resolution | str | None,
    limit: int | None,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, str]:
    """Query parameters of ``GET /prices``; only the values given are sent."""
    params: dict[str, str] = {}
    if resolution is not None:
        try:
            params["resolution"] = Resolution(resolution).value
        except ValueError:
            names = ", ".join(r.value for r in Resolution)
            raise ValidationError(
                f"resolution must be one of {names}, got {resolution!r}"
            ) from None
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BARS:
            raise ValidationError(f"limit must be an int within 1..{MAX_BARS}, got {limit!r}")
        params["max"] = str(limit)
    elif start is not None or end is not None:
        # Without max the server stops at its default of 10 bars, which would cut a window
        # short with no sign of it; the documented maximum is asked for instead.
        params["max"] = str(MAX_BARS)
    if start is not None:
        params["from"] = to_api_time(start, "start")
    if end is not None:
        params["to"] = to_api_time(end, "end")
    if start is not None and end is not None and start > end:
        raise ValidationError("start must not be after end")
    return params
