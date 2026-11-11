"""Market payloads trimmed from the samples in Capital.com's OpenAPI document."""

from copy import deepcopy
from decimal import Decimal
from typing import Any


def _rule(unit: str, value: str) -> dict[str, Any]:
    return {"unit": unit, "value": Decimal(value)}


_SILVER_DETAILS: dict[str, Any] = {
    "instrument": {
        "epic": "SILVER",
        "symbol": "Silver",
        "expiry": "-",
        "name": "Silver",
        "lotSize": 1,
        "type": "COMMODITIES",
        "guaranteedStopAllowed": True,
        "streamingPricesAvailable": True,
        "currency": "USD",
        "marginFactor": 10,
        "marginFactorUnit": "PERCENTAGE",
    },
    "dealingRules": {
        "minStepDistance": _rule("POINTS", "0.001"),
        "minDealSize": _rule("POINTS", "1"),
        "maxDealSize": _rule("POINTS", "100000"),
        "minSizeIncrement": _rule("POINTS", "0.1"),
        "minGuaranteedStopDistance": _rule("PERCENTAGE", "1"),
        "minStopOrProfitDistance": _rule("PERCENTAGE", "0.01"),
        "maxStopOrProfitDistance": _rule("PERCENTAGE", "60"),
        "marketOrderPreference": "AVAILABLE_DEFAULT_ON",
        "trailingStopsPreference": "NOT_AVAILABLE",
    },
    "snapshot": {
        "marketStatus": "TRADEABLE",
        "netChange": Decimal("-0.627"),
        "percentageChange": Decimal("-0.27"),
        "updateTime": "2022-04-06T11:23:00.955",
        "delayTime": 0,
        "bid": Decimal("22.041"),
        "offer": Decimal("22.061"),
        "high": Decimal("22.098"),
        "low": Decimal("21.926"),
        "decimalPlacesFactor": 3,
        "scalingFactor": 1,
        "marketModes": ["REGULAR"],
    },
}


def details(epic: str = "SILVER") -> dict[str, Any]:
    """A ``GET /markets/{epic}`` body; ``epic`` replaces the instrument's epic."""
    payload = deepcopy(_SILVER_DETAILS)
    payload["instrument"]["epic"] = epic
    return payload


def market_row(
    epic: str = "USDJPY", pip_position: int = 2, tick_size: str = "0.001"
) -> dict[str, Any]:
    """One row of ``GET /markets``, a navigation leaf or a watchlist."""
    return {
        "delayTime": 0,
        "epic": epic,
        "symbol": epic,
        "netChange": Decimal("0.21"),
        "lotSize": 1,
        "expiry": "-",
        "instrumentType": "CURRENCIES",
        "instrumentName": epic,
        "high": Decimal("151.2"),
        "low": Decimal("150.1"),
        "percentageChange": Decimal("0.14"),
        "updateTime": "2022-04-06T15:17:38.477",
        "updateTimeUTC": "2022-04-06T13:17:38.477",
        "bid": Decimal("150.512"),
        "offer": Decimal("150.527"),
        "streamingPricesAvailable": True,
        "marketStatus": "TRADEABLE",
        "scalingFactor": 1,
        "marketModes": ["REGULAR"],
        "pipPosition": pip_position,
        "tickSize": Decimal(tick_size),
    }
