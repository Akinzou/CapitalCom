"""Golden rows: opening positions, resolving deal references, ``test_trade``."""

import logging

import pytest
import responses

from tests.legacy.conftest import DEMO, legacy, sent
from tests.legacy.golden.payloads import confirm

POSITIONS = f"{DEMO}/api/v1/positions"
CONFIRM = f"{DEMO}/api/v1/confirms/o_1"


def opened(api: responses.RequestsMock) -> None:
    api.post(POSITIONS, json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirm())


def test_open_raw_position_returns_the_affected_deal_id(api: responses.RequestsMock) -> None:
    opened(api)
    assert legacy().open_raw_position("BTCUSD", 0.0001, "BUY") == "P1"


def test_open_raw_position_sends_the_1_0_4_body(api: responses.RequestsMock) -> None:
    opened(api)
    legacy().open_raw_position("BTCUSD", 0.0001, "BUY", stop_dist=0, profit_dist=None)
    legacy().open_raw_position("BTCUSD", 0.0001, "SELL", stop_dist=500, profit_dist=900.5)
    base = {
        "epic": "BTCUSD",
        "expiry": "-",
        "size": 0.0001,
        "orderType": "MARKET",
        "guaranteedStop": False,
        "forceOpen": True,
    }
    posts = [body for method, _, body in sent(api) if method == "POST"]
    assert posts == [
        base | {"direction": "BUY"},
        base | {"direction": "SELL", "stopDistance": 500, "profitDistance": 900.5},
    ]


def test_open_forex_position_scales_lots_and_pips(api: responses.RequestsMock) -> None:
    opened(api)
    legacy().open_forex_position("EURUSD", 0.001, "BUY", stop_dist=100, profit_dist=200)
    body = next(body for method, _, body in sent(api) if method == "POST")
    assert body["size"] == 0.001 * 100000
    assert body["stopDistance"] == 100 * 10**-5
    assert body["profitDistance"] == 200 * 10**-5


def test_get_deal_by_ref_waits_until_ready(api: responses.RequestsMock) -> None:
    api.get(CONFIRM, status=404, json={"errorCode": "error.not-found.dealReference"})
    api.get(CONFIRM, status=400, json={"errorCode": "error.invalid.dealReference"})
    api.get(CONFIRM, json={"dealReference": "o_1", "dealStatus": "ACCEPTED"})
    api.get(CONFIRM, json=confirm())
    assert legacy().get_deal_by_ref("o_1") == "P1"
    assert len(sent(api)) == 4


def test_get_deal_by_ref_gives_up_after_retries(api: responses.RequestsMock) -> None:
    api.get(CONFIRM, status=404, json={"errorCode": "error.not-found.dealReference"})
    client = legacy()
    with pytest.raises(Exception):  # noqa: B017, PT011 - the type changes in 2.0
        client.get_deal_by_ref("o_1", retries=3, delay=0.1)
    assert len(sent(api)) == 3


def test_open_that_nets_raises(api: responses.RequestsMock) -> None:
    api.post(POSITIONS, json={"dealReference": "o_1"})
    api.get(CONFIRM, json=confirm(affected=()))
    with pytest.raises(Exception):  # noqa: B017, PT011 - the type changes in 2.0
        legacy().open_raw_position("BTCUSD", 0.0001, "SELL")


def test_trade_swallows_open_errors(
    api: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    api.post(POSITIONS, status=500, json={"errorCode": "error.unexpected"})
    with caplog.at_level(logging.INFO):
        legacy().test_trade()
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("Failed to open position" in message for message in errors)
