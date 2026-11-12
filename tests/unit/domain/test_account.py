"""Account read models."""

from decimal import Decimal

import pytest

from capitalcom.domain.account import Account, AccountPreferences, Balance, Leverage
from capitalcom.domain.errors import ResponseFormatError

ACCOUNT = {
    "accountId": "12345678901234567",
    "accountName": "USD",
    "status": "ENABLED",
    "accountType": "CFD",
    "preferred": True,
    "balance": {
        "balance": Decimal("124.95"),
        "deposit": Decimal("125.08"),
        "profitLoss": Decimal("-0.13"),
        "available": Decimal("94.31"),
    },
    "currency": "USD",
    "symbol": "$",
}
PREFERENCES = {
    "hedgingMode": False,
    "leverages": {"SHARES": {"current": 5, "available": [1, 2, 3, 5]}},
}


def test_account_parses_documented_sample() -> None:
    account = Account.from_api(ACCOUNT)
    assert account.account_id == "12345678901234567"
    assert account.preferred is True
    assert account.symbol == "$"
    assert account.balance == Balance(
        Decimal("124.95"), Decimal("125.08"), Decimal("-0.13"), Decimal("94.31")
    )
    assert account.raw == ACCOUNT


def test_unknown_account_type_is_kept_as_string() -> None:
    account = Account.from_api({**ACCOUNT, "accountType": "SPREADBET", "symbol": None})
    assert account.account_type == "SPREADBET"
    assert account.symbol is None


def test_account_with_float_balance_is_rejected() -> None:
    broken = {**ACCOUNT, "balance": {**ACCOUNT["balance"], "available": 94.31}}  # type: ignore[dict-item]
    with pytest.raises(ResponseFormatError, match="available"):
        Account.from_api(broken)


def test_preferences_parse_leverages() -> None:
    preferences = AccountPreferences.from_api(PREFERENCES)
    assert preferences.hedging_mode is False
    assert preferences.leverages == {"SHARES": Leverage(5, (1, 2, 3, 5))}


def test_preferences_with_fractional_leverage_are_rejected() -> None:
    broken = {
        "hedgingMode": False,
        "leverages": {"SHARES": {"current": Decimal("2.5"), "available": []}},
    }
    with pytest.raises(ResponseFormatError, match="current"):
        AccountPreferences.from_api(broken)


def test_leverage_without_current_reports_missing() -> None:
    with pytest.raises(ResponseFormatError) as caught:
        Leverage.from_api({"available": [1, 2]}, "SHARES")
    assert "leverages.SHARES.current" in str(caught.value)
    assert "missing" in str(caught.value)
