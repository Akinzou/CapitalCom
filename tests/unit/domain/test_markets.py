"""Market rows and the navigation tree."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalcom.domain.errors import ResponseFormatError
from capitalcom.domain.markets import Market, MarketNode, NodeContents
from tests.unit.market_payloads import market_row


def test_a_row_parses_with_its_pip_scale() -> None:
    market = Market.from_api(market_row())
    assert market.epic == "USDJPY"
    assert market.instrument_type == "CURRENCIES"
    assert market.pip.size == Decimal("0.01")
    assert market.pips_to_distance(10) == Decimal("0.10")
    assert market.bid == Decimal("150.512")
    assert market.update_time_utc == datetime(2022, 4, 6, 13, 17, 38, 477000, tzinfo=UTC)


def test_a_quote_less_row_parses_with_none() -> None:
    row = market_row()
    for key in ("bid", "offer", "high", "low", "updateTimeUTC"):
        del row[key]
    market = Market.from_api(row)
    assert (market.bid, market.offer, market.high, market.low) == (None,) * 4
    assert market.update_time_utc is None


def test_a_row_without_pip_position_is_refused() -> None:
    row = market_row()
    del row["pipPosition"]
    with pytest.raises(ResponseFormatError, match="pipPosition"):
        Market.from_api(row)


def test_a_category_node_has_no_markets() -> None:
    contents = NodeContents.from_api({"nodes": [{"id": "hierarchy_v1.commons", "name": "Most"}]})
    assert contents.nodes == (MarketNode("hierarchy_v1.commons", "Most"),)
    assert contents.markets == ()


def test_a_leaf_node_lists_its_markets() -> None:
    contents = NodeContents.from_api({"nodes": [], "markets": [market_row("EURUSD", 4)]})
    assert contents.nodes == ()
    assert [m.epic for m in contents.markets] == ["EURUSD"]
