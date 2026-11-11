"""Markets and prices against the demo server. Read-only: nothing here changes the account."""

import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalcom.api.composition import Core
from capitalcom.api.markets import MAX_EPICS, MarketsResource
from capitalcom.api.prices import PricesResource
from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import NotFoundError

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")
UNKNOWN_EPIC = "NOSUCHEPIC999"


def test_all_markets_parse(demo_core: Core) -> None:
    markets = MarketsResource(demo_core).all()
    assert len(markets) > 1000
    log.info("markets: %d, by type: %s", len(markets), Counter(m.instrument_type for m in markets))
    log.info(
        "rows without bid: %d, without updateTimeUTC: %d, pip positions: %s",
        sum(m.bid is None for m in markets),
        sum(m.update_time_utc is None for m in markets),
        sorted({m.pip.position for m in markets}),
    )


def test_navigation_reaches_markets(demo_core: Core) -> None:
    resource = MarketsResource(demo_core)
    nodes = resource.navigation()
    assert nodes
    node_id = nodes[0].node_id
    for depth in range(1, 5):
        contents = resource.browse(node_id, limit=50)
        if contents.markets:
            log.info("markets reached at depth %d: %d rows", depth, len(contents.markets))
            return
        assert contents.nodes, "a navigation node with neither sub-nodes nor markets"
        node_id = contents.nodes[0].node_id
    pytest.fail("no markets within 4 levels of the first top node")


def test_pip_scale_of_fx_pairs(demo_core: Core) -> None:
    resource = MarketsResource(demo_core)
    for epic, size in (("USDJPY", Decimal("0.01")), ("EURUSD", Decimal("0.0001"))):
        found = {market.epic: market for market in resource.search(epic)}
        assert found[epic].pip.size == size
    assert resource.get("USDJPY").instrument.pip_size == Decimal("0.01")


def test_details_of_assorted_markets_parse(demo_core: Core) -> None:
    resource = MarketsResource(demo_core)
    by_type: defaultdict[str, list[str]] = defaultdict(list)
    for market in resource.all():
        by_type[market.instrument_type].append(market.epic)
    # Round robin over the instrument types, so every type is represented in the sample.
    sample: list[str] = []
    while len(sample) < MAX_EPICS and any(by_type.values()):
        for epics in by_type.values():
            if epics and len(sample) < MAX_EPICS:
                sample.append(epics.pop(0))
    found = resource.get_many(sample)
    assert list(found) == sample
    units = Counter(d.dealing_rules.max_stop_or_profit_distance.unit for d in found.values())
    log.info("details parsed: %d, max stop/profit units: %s", len(found), units)


def test_get_many_names_unknown_epics(demo_core: Core) -> None:
    with pytest.raises(NotFoundError, match=UNKNOWN_EPIC):
        MarketsResource(demo_core).get_many(["BTCUSD", UNKNOWN_EPIC])


def test_recent_prices(demo_core: Core) -> None:
    prices = PricesResource(demo_core)
    bars = prices.history("BTCUSD", Resolution.MINUTE, limit=5)
    assert 1 <= len(bars) <= 5
    assert [bar.time for bar in bars] == sorted(bar.time for bar in bars)
    start = datetime(2001, 1, 1, tzinfo=UTC)
    end = datetime(2001, 1, 1, 1, tzinfo=UTC)
    assert prices.history("BTCUSD", Resolution.MINUTE, start=start, end=end) == ()
    with pytest.raises(NotFoundError):
        prices.history(UNKNOWN_EPIC)
