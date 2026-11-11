"""Historical price bars and the rules for their query parameters."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from capitalcom.domain.api_time import window_params
from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import ValidationError
from capitalcom.domain.parsing import require_decimal, require_mapping, require_utc
from capitalcom.domain.request_values import bounded_int

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
        params["max"] = str(bounded_int(limit, "limit", 1, MAX_BARS))
    elif start is not None or end is not None:
        # Without max the server stops at its default of 10 bars, which would cut a window
        # short with no sign of it; the documented maximum is asked for instead.
        params["max"] = str(MAX_BARS)
    return params | window_params(start, end)
