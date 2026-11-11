"""Position and working-order payloads trimmed from the samples in Capital.com's OpenAPI
document; the stop and protection keys follow what the demo server sent (ADR 0010)."""

from decimal import Decimal
from typing import Any

from tests.unit.market_payloads import market_row


def position_item(deal_id: str = "P1", **position: Any) -> dict[str, Any]:
    """One item of ``GET /positions``; ``position`` adds or replaces keys of ``position``.

    Without extra keys the position has no stop or take-profit, so ``stopLevel``,
    ``profitLevel`` and ``trailingStop`` are absent, as the server sends it.
    """
    return {
        "position": {
            "contractSize": 1,
            "createdDate": "2022-04-06T10:49:52.056",
            "createdDateUTC": "2022-04-06T07:49:52.056",
            "dealId": deal_id,
            "dealReference": f"p_{deal_id}",
            "workingOrderId": "W0",
            "size": Decimal("0.0001"),
            "leverage": 2,
            "upl": Decimal("-0.022"),
            "direction": "BUY",
            "level": Decimal("74549.75"),
            "currency": "USD",
            "guaranteedStop": False,
        }
        | position,
        "market": market_row(),
    }


def order_item(deal_id: str = "W1", **data: Any) -> dict[str, Any]:
    """One item of ``GET /workingorders``; ``data`` adds or replaces keys of the order."""
    market = market_row("SILVER")
    del market["pipPosition"], market["tickSize"]
    return {
        "workingOrderData": {
            "dealId": deal_id,
            "direction": "BUY",
            "epic": "SILVER",
            "orderSize": 1,
            "leverage": 10,
            "orderLevel": 20,
            "timeInForce": "GOOD_TILL_DATE",
            "goodTillDate": "2022-06-09T04:01:00.000",
            "goodTillDateUTC": "2022-06-09T01:01:00.000",
            "createdDate": "2022-04-06T12:48:28.114",
            "createdDateUTC": "2022-04-06T09:48:28.114",
            "guaranteedStop": False,
            "orderType": "LIMIT",
            "trailingStop": False,
            "currencyCode": "USD",
        }
        | data,
        "marketData": market,
    }
