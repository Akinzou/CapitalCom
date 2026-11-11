"""Working orders waiting for their level, from ``GET /api/v1/workingorders``."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from capitalcom.domain.enums import Direction
from capitalcom.domain.parsing import (
    as_mapping,
    flag,
    optional_decimal,
    optional_utc,
    require_bool,
    require_decimal,
    require_direction,
    require_list,
    require_mapping,
    require_str,
    require_utc,
)


@dataclass(frozen=True, slots=True)
class WorkingOrder:
    """One LIMIT or STOP order.

    ``order_type`` and ``time_in_force`` stay strings, as other server enumerations do.
    ``stop_distance`` and ``profit_distance`` keep the sign the server lists: a stop
    distance sent as 3724.38 on a BUY order is listed as -3724.38. ``good_till`` is ``None``
    for an order that runs until cancelled. The market data carries no pip scale, so only
    its instrument name is read; the rest stays in ``raw``.
    """

    deal_id: str
    epic: str
    direction: Direction
    size: Decimal
    level: Decimal
    order_type: str
    time_in_force: str
    good_till: datetime | None
    created: datetime
    currency: str
    leverage: Decimal
    guaranteed_stop: bool
    trailing_stop: bool
    stop_distance: Decimal | None
    profit_distance: Decimal | None
    stop_level: Decimal | None
    profit_level: Decimal | None
    instrument_name: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, item: Mapping[str, Any]) -> "WorkingOrder":
        """Build an order from one ``{workingOrderData, marketData}`` item."""
        data = require_mapping(item, "workingOrderData")
        return cls(
            deal_id=require_str(data, "dealId"),
            epic=require_str(data, "epic"),
            direction=require_direction(data, "direction"),
            size=require_decimal(data, "orderSize"),
            level=require_decimal(data, "orderLevel"),
            order_type=require_str(data, "orderType"),
            time_in_force=require_str(data, "timeInForce"),
            good_till=optional_utc(data, "goodTillDateUTC"),
            created=require_utc(data, "createdDateUTC"),
            currency=require_str(data, "currencyCode"),
            leverage=require_decimal(data, "leverage"),
            guaranteed_stop=require_bool(data, "guaranteedStop"),
            trailing_stop=flag(data, "trailingStop"),
            stop_distance=optional_decimal(data, "stopDistance"),
            profit_distance=optional_decimal(data, "profitDistance"),
            stop_level=optional_decimal(data, "stopLevel"),
            profit_level=optional_decimal(data, "profitLevel"),
            instrument_name=require_str(require_mapping(item, "marketData"), "instrumentName"),
            raw=item,
        )


def working_orders_from(body: Mapping[str, Any]) -> tuple[WorkingOrder, ...]:
    """Parse the items listed under ``workingOrders``."""
    items = require_list(body, "workingOrders")
    return tuple(WorkingOrder.from_api(as_mapping(item, "workingOrders[]")) for item in items)
