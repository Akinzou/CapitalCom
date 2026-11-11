"""Positions and working orders on demo: pins the behaviour ADR 0010 relies on.

Logs statuses, flags and price relations only; no deal or account ids.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from capitalcom.api.accounts import AccountsResource
from capitalcom.api.composition import Core
from capitalcom.api.markets import MarketsResource
from capitalcom.api.orders import OrdersResource
from capitalcom.api.positions import PositionsResource
from capitalcom.domain.confirmation import SizeAdjustedError
from capitalcom.domain.enums import Direction, OrderType
from capitalcom.domain.errors import DealRejectedError, NotFoundError, ValidationError
from capitalcom.domain.market_details import MarketDetails
from capitalcom.domain.protection import StopLoss, TakeProfit
from capitalcom.domain.working_orders import WorkingOrder
from tests.contract.conftest import EPIC, Market

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")


def btc_details(core: Core) -> tuple[MarketDetails, Decimal]:
    """BTCUSD details and its bid; skips when the market has no quote."""
    details = MarketsResource(core).get(EPIC)
    if details.snapshot.bid is None:
        pytest.skip(f"{EPIC} has no quote")
    return details, details.snapshot.bid


def price(details: MarketDetails, value: Decimal) -> Decimal:
    """``value`` rounded to the market's price precision."""
    return value.quantize(Decimal(1).scaleb(-details.snapshot.decimal_places_factor))


def test_position_round_trip(demo_core: Core, btc: Market) -> None:
    positions = PositionsResource(demo_core)
    details, bid = btc_details(demo_core)
    distance = price(details, bid * Decimal("0.05"))
    deal = positions.open(
        EPIC,
        Direction.BUY,
        btc.min_size,
        stop=StopLoss(distance=distance),
        profit=TakeProfit(distance=distance),
        instrument=details,
    )
    assert deal.position_id is not None
    opened = positions.get(deal.position_id)
    assert opened.stop_level is not None
    log.info(
        "distances from open level: profit %s, stop %s (sent %s)",
        opened.profit_level - opened.level if opened.profit_level else None,
        opened.level - opened.stop_level,
        distance,
    )
    # Inferred from the probe (ADR 0010): a distance counts from the open level.
    assert opened.profit_level == opened.level + distance

    stop_level = price(details, bid * Decimal("0.9"))
    amended = positions.amend(deal.position_id, stop=StopLoss(level=stop_level), profit=None)
    log.info(
        "amend: status=%s affected=%s", amended.status, [d.status for d in amended.affected_deals]
    )
    after = positions.get(deal.position_id)
    assert (after.stop_level, after.profit_level) == (stop_level, None)

    closed = positions.close(deal.position_id)
    assert [d.status for d in closed.affected_deals] == ["FULLY_CLOSED"]
    with pytest.raises(NotFoundError):
        positions.get(deal.position_id)


def test_position_size_rules(demo_core: Core, btc: Market) -> None:
    positions = PositionsResource(demo_core)
    details, _ = btc_details(demo_core)
    off_grid = btc.min_size * Decimal("1.5")
    with pytest.raises(ValidationError, match="increment"):
        positions.open(EPIC, Direction.BUY, off_grid, instrument=details)

    with pytest.raises(SizeAdjustedError) as adjusted:
        positions.open(EPIC, Direction.BUY, off_grid)
    booked = adjusted.value.confirmation
    log.info("off-grid size %s booked as %s", off_grid, booked.size)
    assert booked.position_id is not None
    positions.close(booked.position_id)

    # Far beyond the margin a demo balance (capped at 100000) can hold, so it is rejected
    # after submission; if it were ever accepted, the btc fixture closes it.
    with pytest.raises(DealRejectedError) as rejected:
        positions.open(EPIC, Direction.BUY, details.dealing_rules.max_deal_size.value)
    log.info("rejection reason: %s", rejected.value.reason)
    assert rejected.value.reason


def test_netting_open(demo_core: Core, btc: Market) -> None:
    if AccountsResource(demo_core).preferences().hedging_mode:
        pytest.skip("hedging mode is on, so opposite deals do not net")
    positions = PositionsResource(demo_core)
    buy = positions.open(EPIC, Direction.BUY, btc.min_size)
    sell = positions.open(EPIC, Direction.SELL, btc.min_size)
    log.info(
        "netting SELL: status=%s affected=%s size=%s",
        sell.status,
        [d.status for d in sell.affected_deals],
        sell.size,
    )
    assert sell.position_id is None
    assert buy.position_id not in {p.deal_id for p in positions.list()}


def listed(orders: OrdersResource, deal_id: str) -> WorkingOrder:
    (order,) = [o for o in orders.list() if o.deal_id == deal_id]
    return order


def test_order_round_trip(demo_core: Core, btc: Market, btc_orders: None) -> None:
    orders = OrdersResource(demo_core)
    details, bid = btc_details(demo_core)
    good_till = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
    level = price(details, bid * Decimal("0.5"))
    deal = orders.create(
        EPIC, Direction.BUY, btc.min_size, level=level, type=OrderType.LIMIT, good_till=good_till
    )
    order_id = deal.deal_id
    assert order_id is not None
    created = listed(orders, order_id)
    assert (created.level, created.good_till, created.order_type) == (level, good_till, "LIMIT")

    lower = price(details, bid * Decimal("0.45"))
    orders.amend(order_id, level=lower, good_till=good_till, stop=None, profit=None)
    amended = listed(orders, order_id)
    assert (amended.level, amended.good_till) == (lower, good_till)
    log.info("amended order: time_in_force=%s", amended.time_in_force)

    cancelled = orders.cancel(order_id)
    assert [d.status for d in cancelled.affected_deals] == ["DELETED"]
    assert order_id not in {o.deal_id for o in orders.list()}
