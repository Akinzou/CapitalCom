"""Open positions, from ``GET /api/v1/positions`` and ``GET /api/v1/positions/{dealId}``."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from capitalcom.domain.enums import Direction
from capitalcom.domain.markets import Market
from capitalcom.domain.parsing import (
    as_mapping,
    flag,
    optional_decimal,
    optional_str,
    require_bool,
    require_decimal,
    require_direction,
    require_list,
    require_mapping,
    require_str,
    require_utc,
)


@dataclass(frozen=True, slots=True)
class Position:
    """One open position and the market it is on.

    ``deal_id`` is the id every later call on the position takes. ``stop_level`` and
    ``profit_level`` are ``None`` when unset; a stop given as a distance or an amount is
    reported as its level. ``trailing_stop`` is ``False`` when the server leaves the key
    out, which it does whenever the position has no stop. ``created`` is read from
    ``createdDateUTC``; the local ``createdDate`` stays in ``raw``.
    """

    deal_id: str
    deal_reference: str
    direction: Direction
    size: Decimal
    level: Decimal
    currency: str
    leverage: Decimal
    upl: Decimal
    contract_size: Decimal
    created: datetime
    guaranteed_stop: bool
    trailing_stop: bool
    stop_level: Decimal | None
    profit_level: Decimal | None
    working_order_id: str | None
    market: Market
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, item: Mapping[str, Any]) -> "Position":
        """Build a position from one ``{position, market}`` item."""
        position = require_mapping(item, "position")
        return cls(
            deal_id=require_str(position, "dealId"),
            deal_reference=require_str(position, "dealReference"),
            direction=require_direction(position, "direction"),
            size=require_decimal(position, "size"),
            level=require_decimal(position, "level"),
            currency=require_str(position, "currency"),
            leverage=require_decimal(position, "leverage"),
            upl=require_decimal(position, "upl"),
            contract_size=require_decimal(position, "contractSize"),
            created=require_utc(position, "createdDateUTC"),
            guaranteed_stop=require_bool(position, "guaranteedStop"),
            trailing_stop=flag(position, "trailingStop"),
            stop_level=optional_decimal(position, "stopLevel"),
            profit_level=optional_decimal(position, "profitLevel"),
            working_order_id=optional_str(position, "workingOrderId"),
            market=Market.from_api(require_mapping(item, "market")),
            raw=item,
        )


def positions_from(body: Mapping[str, Any]) -> tuple[Position, ...]:
    """Parse the items listed under ``positions``."""
    items = require_list(body, "positions")
    return tuple(Position.from_api(as_mapping(item, "positions[]")) for item in items)
