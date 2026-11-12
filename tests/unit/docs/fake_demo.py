"""A stand-in for the demo server, rich enough to run every documented example offline.

Identifiers carry ``SECRET`` so a test can prove an example never prints one: the quick start
runs in public CI logs.
"""

import json
import re
from decimal import Decimal
from itertools import count
from typing import Any

import responses
from requests import PreparedRequest

from tests.unit.api.test_facade import DEMO, TOKENS
from tests.unit.api.test_session_resource import SESSION
from tests.unit.domain.test_history import ACTIVITY
from tests.unit.domain.test_prices import FIRST_BAR
from tests.unit.market_payloads import details, market_row, wire
from tests.unit.trading_payloads import position_item

ACCOUNT_ID = "ACC-SECRET-0193"
POSITION_ID = "POS-SECRET-0055"
ORDER_ID = "ORD-SECRET-0077"

_API = f"{DEMO}/api/v1"
_Reply = tuple[int, dict[str, str], str]


def _btc_details() -> dict[str, Any]:
    payload = details("BTCUSD")
    payload["dealingRules"] |= {
        "minDealSize": {"unit": "POINTS", "value": Decimal("0.0001")},
        "maxDealSize": {"unit": "POINTS", "value": Decimal(50)},
        "minSizeIncrement": {"unit": "POINTS", "value": Decimal("0.0001")},
    }
    wired: dict[str, Any] = wire(payload)
    return wired


class FakeDemo:
    """Registers every route the examples use; trades are confirmed from what was sent."""

    def __init__(self, mock: responses.RequestsMock, *, confirms: bool = True) -> None:
        self._refs = count(1)
        self._confirms_ready = confirms
        self._confirms: dict[str, dict[str, Any]] = {}
        login = {"currentAccountId": ACCOUNT_ID}
        mock.post(f"{_API}/session", json=login, headers=TOKENS)
        mock.delete(f"{_API}/session", json={"status": "SUCCESS"})
        mock.get(f"{_API}/session", json=SESSION | {"accountId": ACCOUNT_ID})
        mock.get(f"{_API}/accounts", json={"accounts": [_account()]})
        mock.get(f"{_API}/history/activity", json={"activities": [ACTIVITY]})
        mock.get(f"{_API}/markets", json=wire({"markets": [market_row("BTCUSD")]}))
        mock.get(f"{_API}/markets/BTCUSD", json=_btc_details())
        bars = {"prices": [FIRST_BAR] * 3, "pipPosition": 0, "tickSize": Decimal("0.01")}
        mock.get(f"{_API}/prices/BTCUSD", json=wire(bars))
        mock.get(f"{_API}/clientsentiment/BTCUSD", json=_sentiment())
        mock.get(f"{_API}/positions", json=wire({"positions": [position_item(POSITION_ID)]}))
        mock.add_callback("GET", re.compile(rf"{_API}/confirms/.+"), self._confirm)
        trades = re.compile(rf"{_API}/(positions|workingorders).*")
        for method in ("POST", "PUT", "DELETE"):
            mock.add_callback(method, trades, self._deal)

    def _deal(self, request: PreparedRequest) -> _Reply:
        reference = f"o_REF-SECRET-{next(self._refs)}"
        body = json.loads(request.body or "{}", parse_float=Decimal)
        size = Decimal(body.get("size", "0.0001"))
        working = "workingorders" in (request.url or "")
        outcome: dict[str, Any] = {
            "dealReference": reference,
            "dealId": "DEAL-SECRET-0001",
            "dealStatus": "ACCEPTED",
            "status": "OPEN",
            "size": float(size),
            "affectedDeals": [] if working else [{"dealId": POSITION_ID, "status": "OPENED"}],
        }
        if request.method == "DELETE":
            outcome |= {"status": "DELETED" if working else "CLOSED", "affectedDeals": []}
        elif request.method == "PUT":
            outcome |= {"status": "AMENDED", "affectedDeals": []}
        if working and request.method == "POST":
            outcome["dealId"] = ORDER_ID
        self._confirms[reference] = outcome
        return 200, {}, json.dumps({"dealReference": reference})

    def _confirm(self, request: PreparedRequest) -> _Reply:
        reference = (request.url or "").rsplit("/", 1)[-1]
        if not self._confirms_ready:
            # What the server answers while a deal is still being processed.
            return 400, {}, json.dumps({"errorCode": "error.invalid.dealReference"})
        return 200, {}, json.dumps(self._confirms[reference])


def _account() -> dict[str, Any]:
    return {
        "accountId": ACCOUNT_ID,
        "accountName": "USD",
        "status": "ENABLED",
        "accountType": "CFD",
        "preferred": True,
        "currency": "USD",
        "balance": {"balance": 1000, "deposit": 1000, "profitLoss": 0, "available": 1000},
    }


def _sentiment() -> dict[str, Any]:
    return {"marketId": "BTCUSD", "longPositionPercentage": 60, "shortPositionPercentage": 40}
