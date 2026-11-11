"""What a caller asks to open: a position at market, or a working order at a level."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from capitalcom.domain.api_time import to_api_time
from capitalcom.domain.enums import Direction, OrderType
from capitalcom.domain.errors import ValidationError
from capitalcom.domain.protection import StopLoss, TakeProfit, protection_body
from capitalcom.domain.request_values import path_segment, positive_quantity


@dataclass(frozen=True, slots=True, init=False)
class OrderRequest:
    """A position to open at market, with its optional stop and take-profit."""

    epic: str
    direction: Direction
    size: Decimal
    stop: StopLoss | None
    profit: TakeProfit | None

    def __init__(
        self,
        epic: str,
        direction: Direction | str,
        size: Decimal | int,
        stop: StopLoss | None = None,
        profit: TakeProfit | None = None,
    ) -> None:
        # The epic travels in the body, but the path-segment rule refuses the same values a
        # server would: blank, non-string, "." and "..".
        path_segment(epic, "epic")
        try:
            side = Direction(direction)
        except ValueError:
            raise ValidationError(f"direction must be BUY or SELL, got {direction!r}") from None
        # Checked here, not only when the body is built, so a bad value fails at construction.
        protection_body(stop, profit)
        object.__setattr__(self, "epic", epic)
        object.__setattr__(self, "direction", side)
        object.__setattr__(self, "size", positive_quantity(size, "size"))
        object.__setattr__(self, "stop", stop)
        object.__setattr__(self, "profit", profit)

    def to_body(self) -> dict[str, Any]:
        """Body of ``POST /positions``; also the common part of a working order."""
        body: dict[str, Any] = {
            "epic": self.epic,
            "direction": self.direction.value,
            "size": self.size,
        }
        return body | protection_body(self.stop, self.profit)


@dataclass(frozen=True, slots=True, init=False)
class WorkingOrderRequest:
    """A LIMIT or STOP order at ``level``, valid until ``good_till`` or until cancelled."""

    order: OrderRequest
    level: Decimal
    type: OrderType
    good_till: datetime | None

    def __init__(
        self,
        order: OrderRequest,
        level: Decimal | int,
        type: OrderType | str,  # noqa: A002 - the API's own name for the order kind
        good_till: datetime | None = None,
    ) -> None:
        if not isinstance(order, OrderRequest):
            raise ValidationError(f"order must be an OrderRequest, got {order!r}")
        try:
            kind = OrderType(type)
        except ValueError:
            raise ValidationError(f"type must be LIMIT or STOP, got {type!r}") from None
        if good_till is not None:
            to_api_time(good_till, "good_till")
        object.__setattr__(self, "order", order)
        object.__setattr__(self, "level", positive_quantity(level, "level"))
        object.__setattr__(self, "type", kind)
        object.__setattr__(self, "good_till", good_till)

    def to_body(self) -> dict[str, Any]:
        """Body of ``POST /workingorders``."""
        body = self.order.to_body() | {"level": self.level, "type": self.type.value}
        if self.good_till is not None:
            body["goodTillDate"] = to_api_time(self.good_till, "good_till")
        return body
