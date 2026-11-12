# Markets and prices

## Finding a market

Markets are named by their epic, such as `BTCUSD`. To find one, search by name or epic:

```python
--8<-- "docs/examples/markets.py:search"
```

`cc.markets.search(term)` returns `Market` rows; a blank term raises `ValidationError`. Other
ways in:

- `cc.markets.all()` returns every market the account can see, about 4000 rows in one
  response.
- `cc.markets.navigation()` returns the top nodes of the market tree, and
  `cc.markets.browse(node_id, limit=...)` the sub-nodes or markets under one node, as a
  `NodeContents` with `nodes` and `markets`. `limit` must be within 1..500.

A `Market` row carries the latest quote. `bid`, `offer`, `high` and `low` are `None` on the
few markets that have no quote: the server leaves those fields out
([ADR 0009](../adr/0009-market-data.md)).

## Market details and dealing rules

```python
--8<-- "docs/examples/markets.py:details"
```

`cc.markets.get(epic)` returns `MarketDetails` with three parts:

- `instrument`: what is traded, with its lot size, currency and pip scale;
- `dealing_rules`: the size and distance limits;
- `snapshot`: the market status and the latest quote.

It costs two requests. The details carry no pip data, so the client also reads the latest
price bar for it. A market without price data gets `instrument.pip` set to `None`; any other
failure of that second read, an unknown epic included, is raised
([ADR 0009](../adr/0009-market-data.md)).

`cc.markets.get_many(epics)` reads up to 50 markets in one request and returns them keyed by
epic, in the order asked. Its items have no pip scale. The server silently drops unknown or
wrong-case epics; the client raises `NotFoundError` naming each one instead.

Each dealing rule is a `RuleValue` with a `value` and a `unit`, and nothing is converted. On
the demo server, sizes and the minimum step distance are in `POINTS`, while the stop and
profit distance limits are in `PERCENTAGE` of a price the documentation does not name
([ADR 0009](../adr/0009-market-data.md)). Pass the details as `instrument=` when you trade to
check a size against them before sending; see [Trading](trading.md).

## Pips

The pip size is `10 ** -pipPosition`: 0.01 for USDJPY and 0.0001 for EURUSD
([ADR 0009](../adr/0009-market-data.md)).

- `details.instrument.pip_size` and `details.instrument.pips_to_distance(pips)` give the pip
  size and turn pips into a price distance. Both raise `ValidationError` when the pip scale
  is unknown, as on items from `get_many`.
- A `Market` row always has a pip scale, in `market.pip`, and offers
  `market.pips_to_distance(pips)` too.
- `details.instrument.lots_to_size(lots)` turns lots into a deal size.

`pips` and `lots` must be `Decimal` or `int`; a `float` raises `ValidationError`.

## Historical prices

```python
--8<-- "docs/examples/markets.py:prices"
```

`cc.prices.history(epic, resolution, limit=..., start=..., end=...)` returns `PriceBar`
objects, oldest first. Each bar has `open`, `high`, `low` and `close` as `BidAsk` pairs, a
`volume`, and its `time` in UTC.

- Without arguments the server returns the last 10 one-minute bars.
- `resolution` is a `Resolution`, from `MINUTE` to `WEEK`.
- `limit` is 1..1000.
- `start` and `end` must be timezone-aware. A window without `limit` asks for up to 1000
  bars; a window holding more is cut at that number, so read a long range in several calls.
- A window without bars returns `()`. An unknown epic still raises `NotFoundError`, so a typo
  is never hidden behind an empty result ([ADR 0009](../adr/0009-market-data.md)).

## Sentiment

```python
--8<-- "docs/examples/markets.py:sentiment"
```

`cc.sentiment.get(epic)` returns the share of clients long and short on a market.
`cc.sentiment.get_many(epics)` reads several markets in one request, keyed by epic in the
order asked. One unknown epic fails the whole call with `NotFoundError`, because the server
answers for none of them ([ADR 0009](../adr/0009-market-data.md)).

## Watchlists

`cc.watchlists` manages the client's lists of markets:

- `cc.watchlists.list()` returns every `Watchlist`, with its `watchlist_id`, `name` and
  whether it is `editable` and `deleteable`.
- `cc.watchlists.create(name, epics)` creates a list; `name` must be 1..20 characters and
  `epics` is optional. It returns a `WatchlistCreation`. Unknown epics do not fail the call:
  the list is created without them and `all_epics_added` is `False`, so you still get the
  `watchlist_id` of the list that now exists.
- `cc.watchlists.get(watchlist_id)` returns the list's markets as `Market` rows.
- `cc.watchlists.add_market(watchlist_id, epic)` adds a market; adding one that is already on
  the list succeeds.
- `cc.watchlists.remove_market(watchlist_id, epic)` removes one market, and
  `cc.watchlists.delete(watchlist_id)` deletes the list.

A change the server does not answer with success raises `ApiError`
([ADR 0009](../adr/0009-market-data.md)).

## Values in URLs

An epic or id placed in a URL is percent-encoded, and a blank value or `.` or `..` raises
`ValidationError` before sending. Without that rule, an empty epic in `remove_market` would
turn into a request that deletes the whole list
([ADR 0009](../adr/0009-market-data.md)).
