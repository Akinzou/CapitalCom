"""``cc.positions``: every trade call is confirmed before it returns."""

import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.confirmation import SizeAdjustedError
from capitalcom.domain.enums import Direction
from capitalcom.domain.errors import DealRejectedError, ValidationError
from capitalcom.domain.protection import StopLoss, TakeProfit
from tests.unit.api.test_facade import DEMO, TOKENS
from tests.unit.domain.test_market_details import btc_details
from tests.unit.market_payloads import wire
from tests.unit.trading_payloads import position_item

POSITIONS = f"{DEMO}/api/v1/positions"
CONFIRM = f"{DEMO}/api/v1/confirms/o_1"


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(f"{DEMO}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        yield mock


def client() -> CapitalCom:
    return CapitalCom("pos-key-0001", "me@example.com", "pos-pw-0001")


def confirmation(size: str = "0.0001", **extra: Any) -> dict[str, Any]:
    return {
        "dealReference": "o_1",
        "dealId": "D1",
        "dealStatus": "ACCEPTED",
        "status": "OPEN",
        "size": float(size),
        "affectedDeals": [{"dealId": "P1", "status": "OPENED"}],
    } | extra


def sent(mock: responses.RequestsMock) -> list[tuple[str, str, Any]]:
    """Method, URL and JSON body of each request after the login."""
    return [
        (c.request.method or "", c.request.url or "", json.loads(c.request.body or "null"))
        for c in mock.calls
        if not (c.request.url or "").endswith("/session")
    ]


def test_open_sends_the_order_and_returns_the_confirmed_position(
    api: responses.RequestsMock,
) -> None:
    api.post(POSITIONS, json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirmation())
    deal = client().positions.open(
        "BTCUSD", Direction.BUY, Decimal("0.0001"), stop=StopLoss(distance=5)
    )
    assert deal.position_id == "P1"
    assert sent(api)[0] == (
        "POST",
        POSITIONS,
        {"epic": "BTCUSD", "direction": "BUY", "size": 0.0001, "stopDistance": 5},
    )


def test_open_raises_a_rejection(api: responses.RequestsMock) -> None:
    api.post(POSITIONS, json={"dealReference": "o_1"})
    rejected = confirmation(dealStatus="REJECTED", affectedDeals=[], rejectReason="RC_X")
    api.get(CONFIRM, json=rejected)
    with pytest.raises(DealRejectedError, match="RC_X"):
        client().positions.open("BTCUSD", "BUY", Decimal("0.0001"))


def test_open_raises_when_the_server_rounded_the_size(api: responses.RequestsMock) -> None:
    api.post(POSITIONS, json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirmation("0.00010"))
    with pytest.raises(SizeAdjustedError) as caught:
        client().positions.open("BTCUSD", "BUY", Decimal("0.00015"))
    assert caught.value.confirmation.position_id == "P1"


def test_open_validates_against_the_instrument_before_sending(
    api: responses.RequestsMock,
) -> None:
    with pytest.raises(ValidationError, match="increment"):
        client().positions.open("BTCUSD", "BUY", Decimal("0.00015"), instrument=btc_details())
    assert len(api.calls) == 0


def test_amend_sends_exactly_the_protection_given(api: responses.RequestsMock) -> None:
    api.put(f"{POSITIONS}/P1", json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirmation(status="AMENDED", affectedDeals=[]))
    client().positions.amend("P1", stop=None, profit=TakeProfit(level=9))
    assert sent(api)[0] == ("PUT", f"{POSITIONS}/P1", {"profitLevel": 9})


def test_amend_without_both_sides_is_a_type_error(api: responses.RequestsMock) -> None:
    with pytest.raises(TypeError):
        client().positions.amend("P1", profit=None)  # type: ignore[call-arg]
    assert len(api.calls) == 0


def test_close_deletes_the_position(api: responses.RequestsMock) -> None:
    api.delete(f"{POSITIONS}/P1", json={"dealReference": "o_1"})
    closed = [{"dealId": "P1", "status": "FULLY_CLOSED"}]
    api.get(CONFIRM, json=confirmation(status="CLOSED", affectedDeals=closed))
    assert client().positions.close("P1").position_id is None
    assert sent(api)[0][:2] == ("DELETE", f"{POSITIONS}/P1")


@pytest.mark.parametrize("call", ["close", "get"])
@pytest.mark.parametrize("position_id", ["", "..", " "])
def test_bad_ids_never_reach_the_server(
    api: responses.RequestsMock, call: str, position_id: str
) -> None:
    with pytest.raises(ValidationError, match="position_id"):
        getattr(client().positions, call)(position_id)
    assert len(api.calls) == 0


def test_list_and_get_parse_positions(api: responses.RequestsMock) -> None:
    api.get(POSITIONS, json=wire({"positions": [position_item("P1"), position_item("P2")]}))
    api.get(f"{POSITIONS}/P1", json=wire(position_item("P1")))
    positions = client().positions
    assert [p.deal_id for p in positions.list()] == ["P1", "P2"]
    assert positions.get("P1").market.epic == "USDJPY"
