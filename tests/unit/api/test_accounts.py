"""``cc.accounts``."""

import json
from collections.abc import Iterator
from decimal import Decimal

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.enums import Environment
from capitalcom.domain.errors import ApiError, ValidationError
from tests.unit.api.test_facade import DEMO, TOKENS, calls

LIVE = Environment.LIVE.rest_url


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        for host in (DEMO, LIVE):
            mock.post(f"{host}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        yield mock


def client(environment: Environment = Environment.DEMO) -> CapitalCom:
    return CapitalCom("acc-key-0001", "me@example.com", "acc-pw-0001", environment)


def sent_body(mock: responses.RequestsMock) -> object:
    body = mock.calls[-1].request.body
    assert body is not None
    return json.loads(body)


def test_list_returns_accounts(api: responses.RequestsMock) -> None:
    api.get(
        f"{DEMO}/api/v1/accounts",
        json={
            "accounts": [
                {
                    "accountId": "A",
                    "accountName": "USD",
                    "status": "ENABLED",
                    "accountType": "CFD",
                    "preferred": True,
                    "currency": "USD",
                    "balance": {"balance": 1, "deposit": 1, "profitLoss": 0, "available": 1},
                }
            ]
        },
    )
    (account,) = client().accounts.list()
    assert account.account_id == "A"
    assert account.balance.available == Decimal(1)


def test_preferences_are_read(api: responses.RequestsMock) -> None:
    api.get(
        f"{DEMO}/api/v1/accounts/preferences",
        json={
            "hedgingMode": True,
            "leverages": {"SHARES": {"current": 5, "available": [1, 5]}},
        },
    )
    preferences = client().accounts.preferences()
    assert preferences.hedging_mode is True
    assert preferences.leverages["SHARES"].current == 5


def test_update_preferences_sends_only_given_fields(api: responses.RequestsMock) -> None:
    api.put(f"{DEMO}/api/v1/accounts/preferences", json={"status": "SUCCESS"})
    cc = client()
    cc.accounts.update_preferences(leverages={"SHARES": 5})
    assert sent_body(api) == {"leverages": {"SHARES": 5}}
    cc.accounts.update_preferences(hedging_mode=False)
    assert sent_body(api) == {"hedgingMode": False}


@pytest.mark.parametrize(
    "kwargs", [{}, {"leverages": {"SHARES": True}}, {"leverages": {"SHARES": Decimal(5)}}]
)
def test_update_preferences_with_invalid_arguments_raises(
    api: responses.RequestsMock, kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        client().accounts.update_preferences(**kwargs)  # type: ignore[arg-type]
    assert calls(api) == []


def test_update_preferences_not_successful_raises(api: responses.RequestsMock) -> None:
    api.put(f"{DEMO}/api/v1/accounts/preferences", json={"status": "FAILED"})
    with pytest.raises(ApiError, match="FAILED"):
        client().accounts.update_preferences(hedging_mode=True)


def test_top_up_sends_amount(api: responses.RequestsMock) -> None:
    api.post(f"{DEMO}/api/v1/accounts/topUp", json={"successful": True})
    client().accounts.top_up(Decimal("100.5"))
    assert sent_body(api) == {"amount": 100.5}


def test_top_up_on_live_sends_nothing(api: responses.RequestsMock) -> None:
    with pytest.raises(ValidationError, match="demo"):
        client(Environment.LIVE).accounts.top_up(100)
    assert calls(api) == []


@pytest.mark.parametrize(
    "amount", [400001, Decimal("-400000.01"), True, Decimal("NaN"), Decimal("sNaN")]
)
def test_top_up_out_of_range_raises(api: responses.RequestsMock, amount: Decimal) -> None:
    with pytest.raises(ValidationError):
        client().accounts.top_up(amount)
    assert calls(api) == []


def test_top_up_not_successful_raises(api: responses.RequestsMock) -> None:
    api.post(f"{DEMO}/api/v1/accounts/topUp", json={"successful": False})
    with pytest.raises(ApiError, match="successful"):
        client().accounts.top_up(10)
