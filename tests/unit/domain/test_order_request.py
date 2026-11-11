"""Order requests: checked when built, so nothing invalid is ever sent."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from capitalcom.domain.enums import Direction, OrderType
from capitalcom.domain.errors import ValidationError
from capitalcom.domain.order_request import OrderRequest, WorkingOrderRequest
from capitalcom.domain.protection import StopLoss, TakeProfit


def order() -> OrderRequest:
    return OrderRequest("BTCUSD", "BUY", Decimal("0.0001"))


def test_body_carries_the_order_and_its_protection() -> None:
    request = OrderRequest("BTCUSD", "BUY", Decimal("0.0001"), profit=TakeProfit(level=9))
    assert request.direction is Direction.BUY
    assert request.to_body() == {
        "epic": "BTCUSD",
        "direction": "BUY",
        "size": Decimal("0.0001"),
        "profitLevel": Decimal(9),
    }


def test_an_int_size_is_stored_as_decimal() -> None:
    request = OrderRequest("BTCUSD", Direction.SELL, 2, stop=StopLoss(distance=5))
    assert isinstance(request.size, Decimal)
    assert request.to_body()["stopDistance"] == Decimal(5)


@pytest.mark.parametrize(
    ("epic", "direction", "size"),
    [
        ("..", "BUY", 1),
        ("", "BUY", 1),
        ("BTCUSD", "HOLD", 1),
        ("BTCUSD", "BUY", 0),
        ("BTCUSD", "BUY", -1),
        ("BTCUSD", "BUY", 0.5),
        ("BTCUSD", "BUY", True),
    ],
)
def test_invalid_orders_raise(epic: str, direction: str, size: object) -> None:
    with pytest.raises(ValidationError):
        OrderRequest(epic, direction, size)  # type: ignore[arg-type]


def test_protection_of_the_wrong_type_raises() -> None:
    with pytest.raises(ValidationError, match="stop"):
        OrderRequest("BTCUSD", "BUY", 1, stop=TakeProfit(level=1))  # type: ignore[arg-type]


def test_working_order_sends_good_till_in_utc() -> None:
    good_till = datetime(2030, 1, 1, 2, tzinfo=timezone(timedelta(hours=2)))
    request = WorkingOrderRequest(order(), 20, "LIMIT", good_till)
    assert request.type is OrderType.LIMIT
    assert request.to_body() == {
        "epic": "BTCUSD",
        "direction": "BUY",
        "size": Decimal("0.0001"),
        "level": Decimal(20),
        "type": "LIMIT",
        "goodTillDate": "2030-01-01T00:00:00",
    }


def test_working_order_without_good_till_sends_no_date() -> None:
    assert "goodTillDate" not in WorkingOrderRequest(order(), 20, OrderType.STOP).to_body()


@pytest.mark.parametrize(
    ("level", "type_", "good_till"),
    [
        (20, "MARKET", None),
        (0, "LIMIT", None),
        (20.5, "LIMIT", None),
        (20, "LIMIT", datetime(2030, 1, 1)),  # noqa: DTZ001 - the naive value under test
    ],
)
def test_invalid_working_orders_raise(level: object, type_: str, good_till: object) -> None:
    with pytest.raises(ValidationError):
        WorkingOrderRequest(order(), level, type_, good_till)  # type: ignore[arg-type]


def test_working_order_needs_an_order_request() -> None:
    with pytest.raises(ValidationError, match="order"):
        WorkingOrderRequest({"epic": "BTCUSD"}, 20, "LIMIT")  # type: ignore[arg-type]


def test_aware_utc_good_till_is_sent_unchanged() -> None:
    good_till = datetime(2030, 1, 1, tzinfo=UTC)
    body = WorkingOrderRequest(order(), 20, "STOP", good_till).to_body()
    assert body["goodTillDate"] == "2030-01-01T00:00:00"
