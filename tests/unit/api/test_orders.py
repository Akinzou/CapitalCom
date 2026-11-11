"""``cc.orders``: LIMIT and STOP orders, confirmed like positions."""

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.confirmation import SizeAdjustedError
from capitalcom.domain.errors import ValidationError
from capitalcom.domain.protection import StopLoss
from tests.unit.api.test_facade import DEMO, TOKENS
from tests.unit.domain.test_market_details import btc_details
from tests.unit.market_payloads import wire
from tests.unit.trading_payloads import order_item

ORDERS = f"{DEMO}/api/v1/workingorders"
CONFIRM = f"{DEMO}/api/v1/confirms/o_1"
PLUS_TWO = timezone(timedelta(hours=2))


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(f"{DEMO}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        yield mock


def client() -> CapitalCom:
    return CapitalCom("ord-key-0001", "me@example.com", "ord-pw-0001")


def confirmation(status: str = "OPEN", size: str = "0.0001") -> dict[str, Any]:
    return {
        "dealReference": "o_1",
        "dealId": "W1",
        "dealStatus": "ACCEPTED",
        "status": status,
        "size": float(size),
        "affectedDeals": [{"dealId": "W1", "status": "OPENED" if status == "OPEN" else status}],
    }


def sent(mock: responses.RequestsMock) -> list[tuple[str, str, Any]]:
    """Method, URL and JSON body of each request after the login."""
    return [
        (c.request.method or "", c.request.url or "", json.loads(c.request.body or "null"))
        for c in mock.calls
        if not (c.request.url or "").endswith("/session")
    ]


def test_create_sends_good_till_in_utc(api: responses.RequestsMock) -> None:
    api.post(ORDERS, json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirmation())
    deal = client().orders.create(
        "BTCUSD",
        "BUY",
        Decimal("0.0001"),
        level=30000,
        type="LIMIT",
        good_till=datetime(2030, 1, 1, 2, tzinfo=PLUS_TWO),
        stop=StopLoss(distance=500),
    )
    assert (deal.deal_id, deal.position_id) == ("W1", "W1")
    assert sent(api)[0] == (
        "POST",
        ORDERS,
        {
            "epic": "BTCUSD",
            "direction": "BUY",
            "size": 0.0001,
            "stopDistance": 500,
            "level": 30000,
            "type": "LIMIT",
            "goodTillDate": "2030-01-01T00:00:00",
        },
    )


def test_create_raises_when_the_server_rounded_the_size(api: responses.RequestsMock) -> None:
    api.post(ORDERS, json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirmation(size="0.00010"))
    with pytest.raises(SizeAdjustedError):
        client().orders.create("BTCUSD", "BUY", Decimal("0.00015"), level=1, type="STOP")


def test_create_validates_against_the_instrument_before_sending(
    api: responses.RequestsMock,
) -> None:
    with pytest.raises(ValidationError, match="maximum"):
        client().orders.create("BTCUSD", "BUY", 51, level=1, type="LIMIT", instrument=btc_details())
    assert len(api.calls) == 0


def test_amend_sends_only_what_was_given(api: responses.RequestsMock) -> None:
    api.put(f"{ORDERS}/W1", json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirmation("AMENDED"))
    client().orders.amend("W1", good_till=None, stop=None, profit=None, level=25000)
    assert sent(api)[0] == ("PUT", f"{ORDERS}/W1", {"level": 25000})


def test_amend_sends_good_till_in_utc(api: responses.RequestsMock) -> None:
    api.put(f"{ORDERS}/W1", json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirmation("AMENDED"))
    good_till = datetime(2030, 1, 1, 2, tzinfo=PLUS_TWO)
    client().orders.amend("W1", good_till=good_till, stop=None, profit=None)
    assert sent(api)[0][2] == {"goodTillDate": "2030-01-01T00:00:00"}


def test_amend_without_good_till_is_a_type_error(api: responses.RequestsMock) -> None:
    with pytest.raises(TypeError):
        client().orders.amend("W1", stop=None, profit=None)  # type: ignore[call-arg]
    assert len(api.calls) == 0


@pytest.mark.parametrize(
    ("good_till", "level"),
    [(datetime(2030, 1, 1), None), (None, 0), (None, 1.5)],  # noqa: DTZ001 - naive under test
)
def test_amend_refuses_bad_values_before_sending(
    api: responses.RequestsMock, good_till: object, level: object
) -> None:
    with pytest.raises(ValidationError):
        client().orders.amend(
            "W1",
            good_till=good_till,  # type: ignore[arg-type]
            stop=None,
            profit=None,
            level=level,  # type: ignore[arg-type]
        )
    assert len(api.calls) == 0


def test_cancel_deletes_the_order(api: responses.RequestsMock) -> None:
    api.delete(f"{ORDERS}/W1", json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirmation("DELETED"))
    assert client().orders.cancel("W1").deal_id == "W1"
    assert sent(api)[0][:2] == ("DELETE", f"{ORDERS}/W1")


@pytest.mark.parametrize("order_id", ["", "..", "."])
def test_bad_ids_never_reach_the_server(api: responses.RequestsMock, order_id: str) -> None:
    with pytest.raises(ValidationError, match="order_id"):
        client().orders.cancel(order_id)
    with pytest.raises(ValidationError, match="order_id"):
        client().orders.amend(order_id, good_till=None, stop=None, profit=None)
    assert len(api.calls) == 0


def test_list_parses_orders(api: responses.RequestsMock) -> None:
    api.get(ORDERS, json=wire({"workingOrders": [order_item("W1"), order_item("W2")]}))
    assert [o.deal_id for o in client().orders.list()] == ["W1", "W2"]


def test_amend_refuses_a_string_good_till(api: responses.RequestsMock) -> None:
    with pytest.raises(ValidationError, match="good_till"):
        client().orders.amend(
            "W1",
            good_till="2030-01-01T00:00:00",  # type: ignore[arg-type]
            stop=None,
            profit=None,
        )
    assert len(api.calls) == 0
