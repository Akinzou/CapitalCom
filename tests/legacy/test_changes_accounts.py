"""Changed rows of legacy account calls (spec §7 change 3; plan rulings 10 and 12). Each
test here failed against 1.0.4."""

from decimal import Decimal

import pytest
import responses

from capitalcom.domain.errors import ApiError, CapitalComError, NotFoundError
from tests.legacy.conftest import DEMO, legacy

ACCOUNTS = f"{DEMO}/api/v1/accounts"


def test_http_errors_are_typed(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, status=500, json={"errorCode": "error.unexpected"})
    api.get(f"{DEMO}/api/v1/positions", status=404, json={"errorCode": "error.not-found"})
    client = legacy()
    with pytest.raises(ApiError):
        client.get_balance()
    with pytest.raises(NotFoundError):
        client.get_open_positions()


def test_no_accounts_is_capitalcom_error(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": []})
    with pytest.raises(CapitalComError, match="No accounts found"):
        legacy().get_balance()


def test_unsuccessful_top_up_raises(api: responses.RequestsMock) -> None:
    api.post(f"{ACCOUNTS}/topUp", json={"successful": False})
    with pytest.raises(ApiError, match="top-up"):
        legacy().top_up_demo(1000.5)


def test_floats_are_exact() -> None:
    from capitalcom.legacy.accounts import as_floats

    value = {"a": [Decimal("1.0712"), 3, "x", None, True], "b": {"c": Decimal("74549.75")}}
    assert as_floats(value) == {"a": [1.0712, 3, "x", None, True], "b": {"c": 74549.75}}
    assert isinstance(as_floats(Decimal("2")), float)
