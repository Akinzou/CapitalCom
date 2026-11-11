"""Open positions and working orders as the server lists them."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalcom.domain.enums import Direction
from capitalcom.domain.errors import ResponseFormatError
from capitalcom.domain.positions import Position, positions_from
from capitalcom.domain.working_orders import WorkingOrder, working_orders_from
from tests.unit.trading_payloads import order_item, position_item


def test_a_position_without_protection_parses() -> None:
    position = Position.from_api(position_item())
    assert position.deal_id == "P1"
    assert position.direction is Direction.BUY
    assert position.level == Decimal("74549.75")
    assert position.created == datetime(2022, 4, 6, 7, 49, 52, 56000, tzinfo=UTC)
    assert position.market.pip.size == Decimal("0.01")
    assert position.stop_level is None
    assert position.profit_level is None
    assert position.trailing_stop is False
    assert position.working_order_id == "W0"


def test_a_position_with_protection_parses() -> None:
    item = position_item(
        stopLevel=Decimal("67047.44"), profitLevel=Decimal("82001.86"), trailingStop=False
    )
    position = Position.from_api(item)
    assert position.stop_level == Decimal("67047.44")
    assert position.profit_level == Decimal("82001.86")


def test_positions_from_reads_every_item() -> None:
    body = {"positions": [position_item("P1"), position_item("P2")]}
    assert [p.deal_id for p in positions_from(body)] == ["P1", "P2"]
    assert positions_from({"positions": []}) == ()


def test_a_position_without_a_deal_id_is_named() -> None:
    item = position_item()
    del item["position"]["dealId"]
    with pytest.raises(ResponseFormatError, match="dealId"):
        Position.from_api(item)


def test_a_non_bool_trailing_flag_is_refused() -> None:
    with pytest.raises(ResponseFormatError, match="trailingStop"):
        Position.from_api(position_item(trailingStop="no"))


def test_a_working_order_parses_with_its_signed_distance() -> None:
    order = WorkingOrder.from_api(order_item(stopDistance=Decimal("-3724.38")))
    assert order.deal_id == "W1"
    assert order.stop_distance == Decimal("-3724.38")
    assert order.profit_distance is None
    assert order.good_till == datetime(2022, 6, 9, 1, 1, tzinfo=UTC)
    assert order.order_type == "LIMIT"
    assert order.size == Decimal(1)
    assert order.level == Decimal(20)
    assert order.instrument_name == "SILVER"
    assert order.currency == "USD"


def test_a_good_till_cancelled_order_has_no_date() -> None:
    item = order_item(timeInForce="GOOD_TILL_CANCELLED")
    del item["workingOrderData"]["goodTillDate"], item["workingOrderData"]["goodTillDateUTC"]
    order = WorkingOrder.from_api(item)
    assert order.good_till is None
    assert order.time_in_force == "GOOD_TILL_CANCELLED"


def test_working_orders_from_reads_every_item() -> None:
    body = {"workingOrders": [order_item("W1"), order_item("W2")]}
    assert [o.deal_id for o in working_orders_from(body)] == ["W1", "W2"]


def test_an_order_without_a_deal_id_is_named() -> None:
    item = order_item()
    del item["workingOrderData"]["dealId"]
    with pytest.raises(ResponseFormatError, match="dealId"):
        WorkingOrder.from_api(item)


def test_an_unknown_direction_is_named() -> None:
    with pytest.raises(ResponseFormatError, match="direction"):
        Position.from_api(position_item(direction="HOLD"))
