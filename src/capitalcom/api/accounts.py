"""``cc.accounts``: balances, preferences and demo top-up."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from capitalcom.api.composition import Core
from capitalcom.domain.account import Account, AccountPreferences
from capitalcom.domain.enums import Environment
from capitalcom.domain.errors import ApiError, ValidationError
from capitalcom.domain.parsing import as_mapping, check_success, require_list
from capitalcom.domain.request_values import caller_quantity

# Documented bounds of POST /accounts/topUp; checked locally so a typo fails before it
# spends one of the 100 top-ups a demo account gets per day.
MAX_TOP_UP = Decimal(400000)


class AccountsResource:
    """The client's accounts."""

    def __init__(self, core: Core) -> None:
        self._core = core

    def list(self) -> tuple[Account, ...]:
        """All accounts of the client (``GET /api/v1/accounts``)."""
        body = as_mapping(self._core.api.call("GET", "/api/v1/accounts").unwrap(), "accounts")
        items = require_list(body, "accounts")
        return tuple(Account.from_api(as_mapping(item, "accounts[]")) for item in items)

    def preferences(self) -> AccountPreferences:
        """Hedging mode and leverage per instrument class."""
        body = self._core.api.call("GET", "/api/v1/accounts/preferences").unwrap()
        return AccountPreferences.from_api(as_mapping(body, "preferences"))

    def update_preferences(
        self,
        *,
        leverages: Mapping[str, int] | None = None,
        hedging_mode: bool | None = None,
    ) -> None:
        """Change leverages and/or hedging mode; only the arguments given are sent."""
        body: dict[str, Any] = {}
        if leverages is not None:
            for name, value in leverages.items():
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValidationError(f"leverage for {name!r} must be an int, got {value!r}")
            body["leverages"] = dict(leverages)
        if hedging_mode is not None:
            body["hedgingMode"] = hedging_mode
        if not body:
            raise ValidationError("give leverages, hedging_mode or both")
        answer = self._core.api.call("PUT", "/api/v1/accounts/preferences", json=body).unwrap()
        check_success(answer, "preferences not updated")

    def top_up(self, amount: Decimal | int) -> None:
        """Add ``amount`` (negative to withdraw) to a demo account's balance.

        Demo only: the server allows 100 top-ups a day and caps the balance at 100000.
        """
        if self._core.environment is not Environment.DEMO:
            raise ValidationError("top_up is available on demo accounts only")
        if abs(caller_quantity(amount, "amount")) > MAX_TOP_UP:
            raise ValidationError(f"amount must be within ±{MAX_TOP_UP}, got {amount}")
        answer = self._core.api.call(
            "POST", "/api/v1/accounts/topUp", json={"amount": amount}
        ).unwrap()
        if not isinstance(answer, Mapping) or answer.get("successful") is not True:
            raise ApiError(200, None, f"top-up not successful: {answer!r}")
