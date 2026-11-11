"""Recorded response shapes for the golden suite (ADRs 0007-0010); no real ids or balances."""

from typing import Any

from tests.unit.market_payloads import wire
from tests.unit.trading_payloads import position_item


def confirm(
    ref: str = "o_1",
    *,
    status: str = "ACCEPTED",
    affected: tuple[tuple[str, str], ...] = (("P1", "OPENED"),),
    deal_id: str | None = "D1",
    size: float | None = None,
) -> dict[str, Any]:
    """A ``/confirms`` answer; ``REJECTED`` comes, as on demo, with no affected deals."""
    body: dict[str, Any] = {
        "dealReference": ref,
        "dealStatus": status,
        "status": "DELETED" if status == "REJECTED" else "OPEN",
        "affectedDeals": [{"dealId": i, "status": s} for i, s in affected],
    }
    if deal_id is not None:
        body["dealId"] = deal_id
    if size is not None:
        body["size"] = size
    if status == "REJECTED":
        body["rejectReason"] = "RC_NOT_ENOUGH_MARGIN"
    return body


def account(account_id: str, balance: float, currency: str = "USD") -> dict[str, Any]:
    """One item of ``GET /accounts``; ``available`` sits inside ``balance``, not beside it."""
    return {
        "accountId": account_id,
        "accountName": "CFD",
        "status": "ENABLED",
        "accountType": "CFD",
        "preferred": True,
        "currency": currency,
        "balance": {
            "balance": balance,
            "deposit": balance,
            "profitLoss": 0.0,
            "available": balance,
        },
    }


def position_row(deal_id: str, level: float) -> dict[str, Any]:
    """One item of ``GET /positions`` as the server sends it, numbers as JSON numbers."""
    row: dict[str, Any] = wire(position_item(deal_id))
    row["position"]["level"] = level
    return row
