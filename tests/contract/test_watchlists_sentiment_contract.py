"""Client sentiment and a watchlist round trip against the demo server.

The only state created is one watchlist named with ``PREFIX``; it is deleted in ``finally``,
and leftovers of an interrupted run are swept first. Names and ids are never logged.
"""

import logging
from decimal import Decimal
from secrets import token_hex

import pytest

from capitalcom.api.composition import Core
from capitalcom.api.sentiment import SentimentResource
from capitalcom.api.watchlists import WatchlistsResource
from capitalcom.domain.errors import NotFoundError

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")
PREFIX = "cc-contract-"


def test_sentiment(demo_core: Core) -> None:
    resource = SentimentResource(demo_core)
    one = resource.get("BTCUSD")
    assert abs(one.long_percentage + one.short_percentage - 100) <= Decimal("0.02")
    assert set(resource.get_many(["BTCUSD", "EURUSD"])) == {"BTCUSD", "EURUSD"}


def test_watchlist_round_trip(demo_core: Core) -> None:
    lists = WatchlistsResource(demo_core)
    stale = [w.watchlist_id for w in lists.list() if w.name.startswith(PREFIX)]
    for watchlist_id in stale:
        lists.delete(watchlist_id)
    log.info("stale contract watchlists removed: %d", len(stale))

    created = lists.create(f"{PREFIX}{token_hex(3)}", ["BTCUSD", "NOSUCHEPIC999"])
    watchlist_id = created.watchlist_id
    try:
        assert created.all_epics_added is False
        assert [m.epic for m in lists.get(watchlist_id)] == ["BTCUSD"]
        lists.add_market(watchlist_id, "ETHUSD")
        assert {m.epic for m in lists.get(watchlist_id)} == {"BTCUSD", "ETHUSD"}
        lists.remove_market(watchlist_id, "ETHUSD")
        assert [m.epic for m in lists.get(watchlist_id)] == ["BTCUSD"]
    finally:
        lists.delete(watchlist_id)
    with pytest.raises(NotFoundError):
        lists.get(watchlist_id)
