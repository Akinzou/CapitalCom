"""Golden rows: positions, balances, accounts and demo top-up as raw 1.0.4 shapes."""

import logging

import pytest
import responses

from tests.legacy.golden.conftest import DEMO, legacy, sent
from tests.legacy.golden.payloads import account, position_row

ACCOUNTS = f"{DEMO}/api/v1/accounts"
TWO = {"accounts": [account("A", 1000.5), account("B", 20.25, "EUR")]}


def test_get_open_positions_returns_raw_dicts_with_floats(api: responses.RequestsMock) -> None:
    rows = [position_row("P1", 1.0712), position_row("P2", 74549.75)]
    api.get(f"{DEMO}/api/v1/positions", json={"positions": rows})
    positions = legacy().get_open_positions()
    assert positions == rows
    assert isinstance(positions[0]["position"]["level"], float)


def test_get_balance_picks_the_account_or_the_first(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json=TWO)
    client = legacy()
    assert client.get_balance() == 1000.5
    assert client.get_balance("B") == 20.25
    assert client.get_balance("unknown") == 1000.5


def test_get_balance_raw_shape(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json=TWO)
    assert legacy().get_balance("B", raw=True) == {
        "balance": TWO["accounts"][1]["balance"],
        "available": None,
        "currency": "EUR",
    }


def test_get_balance_without_accounts_raises(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": []})
    with pytest.raises(Exception, match="No accounts found"):
        legacy().get_balance()


def test_list_accounts_returns_raw_dicts_and_logs_each(
    api: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    api.get(ACCOUNTS, json=TWO)
    client = legacy()
    with caplog.at_level(logging.INFO):
        assert client.list_accounts() == TWO["accounts"]
    logged = [r.getMessage() for r in caplog.records if "Account ID" in r.getMessage()]
    assert len(logged) == 2


def test_list_accounts_empty_returns_empty_list(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": []})
    assert legacy().list_accounts() == []


def test_top_up_demo_returns_none(api: responses.RequestsMock) -> None:
    api.post(f"{ACCOUNTS}/topUp", json={"successful": True})
    legacy().top_up_demo(1000)
    assert sent(api) == [("POST", f"{ACCOUNTS}/topUp", {"amount": 1000})]


def test_http_error_raises(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, status=500, json={"errorCode": "error.unexpected"})
    with pytest.raises(Exception):  # noqa: B017, PT011 - the type changes in 2.0
        legacy().get_balance()
