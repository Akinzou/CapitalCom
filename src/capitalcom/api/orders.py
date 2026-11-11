"""``cc.orders``: LIMIT and STOP working orders."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from capitalcom.api.composition import Core
from capitalcom.api.dealing import submit
from capitalcom.domain.api_time import to_api_time
from capitalcom.domain.confirmation import DealConfirmation
from capitalcom.domain.enums import Direction, OrderType
from capitalcom.domain.market_details import MarketDetails
from capitalcom.domain.order_request import OrderRequest, WorkingOrderRequest
from capitalcom.domain.parsing import as_mapping
from capitalcom.domain.protection import StopLoss, TakeProfit, protection_body
from capitalcom.domain.request_values import path_segment, positive_quantity
from capitalcom.domain.working_orders import WorkingOrder, working_orders_from

_ROOT = "/api/v1/workingorders"


class OrdersResource:
    """Working orders of the current account."""

    def __init__(self, core: Core) -> None:
        self._core = core

    def list(self) -> tuple[WorkingOrder, ...]:
        """Every working order."""
        body = self._core.api.call("GET", _ROOT).unwrap()
        return working_orders_from(as_mapping(body, "workingOrders"))

    def create(
        self,
        epic: str,
        direction: Direction | str,
        size: Decimal | int,
        *,
        level: Decimal | int,
        type: OrderType | str,  # noqa: A002 - the API's own name for the order kind
        good_till: datetime | None = None,
        stop: StopLoss | None = None,
        profit: TakeProfit | None = None,
        instrument: MarketDetails | None = None,
    ) -> DealConfirmation:
        """Place a LIMIT or STOP order at ``level`` and return its confirmation.

        The order's id is ``confirmation.deal_id``. Without ``good_till`` the order runs
        until cancelled. With ``instrument`` the size is checked against the dealing rules
        first. ``SizeAdjustedError`` means the server booked another size; the order exists.
        """
        order = OrderRequest(epic, direction, size, stop, profit)
        request = WorkingOrderRequest(order, level, type, good_till)
        if instrument is not None:
            instrument.validate(order)
        confirmation = submit(self._core, "POST", _ROOT, request.to_body())
        return confirmation.require_size(order.size)

    def amend(
        self,
        order_id: str,
        *,
        good_till: datetime | None,
        stop: StopLoss | None,
        profit: TakeProfit | None,
        level: Decimal | int | None = None,
    ) -> DealConfirmation:
        """Change the order; replaces its expiry and all protection.

        The server drops whatever the request leaves out: without ``good_till`` the order
        becomes good until cancelled, and a stop or take-profit not passed again is removed.
        Only ``level`` is kept when omitted.
        """
        path = self._path(order_id)
        body: dict[str, Any] = {}
        if level is not None:
            body["level"] = positive_quantity(level, "level")
        if good_till is not None:
            body["goodTillDate"] = to_api_time(good_till, "good_till")
        return submit(self._core, "PUT", path, body | protection_body(stop, profit))

    def cancel(self, order_id: str) -> DealConfirmation:
        """Delete the order."""
        return submit(self._core, "DELETE", self._path(order_id))

    @staticmethod
    def _path(order_id: str) -> str:
        return f"{_ROOT}/{path_segment(order_id, 'order_id')}"
