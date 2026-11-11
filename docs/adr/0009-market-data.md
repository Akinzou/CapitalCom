# 9. Market data: markets, prices, sentiment and watchlists

- Status: accepted
- Date: 2026-11-11

## Context

Stage 2b adds four namespaces: `cc.markets`, `cc.prices`, `cc.sentiment` and `cc.watchlists`.
The published documentation describes them only in part. Five demo probe runs and the
OpenAPI document embedded in the documentation page filled the gaps:

- `GET /markets?epics=A,B` answers `{"marketDetails": [...]}`, not the documented `markets`.
  It keeps request order, collapses duplicates, and silently drops unknown or wrong-case
  epics.
- Market rows (listing, search, navigation leaves, watchlists) carry `pipPosition` and
  `tickSize`. Market details (`GET /markets/{epic}`) carry neither. `GET /prices/{epic}` does,
  even with `max=1` on a closed market.
- A few of the 4011 demo markets have no quote. Three rows lack `bid`, `offer` and
  `percentageChange`, 80 lack `high`, `low` and `netChange`, and one lacks `updateTimeUTC`.
  The fields are absent, never `null`.
- A price window without bars answers 404 `error.prices.not-found`. An unknown epic answers
  404 `error.not-found.epic`.
- A batch sentiment call with one unknown id fails as a whole with a 404. An empty
  `marketIds=` answers 500.
- Creating a watchlist with an unknown epic answers 200 `SUCCESS_NOT_ALL_INSTRUMENTS_ADDED`
  and creates the list without that epic.

## Decisions

### Caller values in URLs pass one rule

Every id or epic placed in a URL path goes through `path_segment`. It must be a non-blank
string, and it is percent-encoded with no safe characters. `.` and `..` are refused rather
than encoded, because URL normalisation would collapse them into a parent path:
`remove_market("..", "session")` would otherwise reach `DELETE /api/v1/session`. An empty
epic in `remove_market` would otherwise turn into `DELETE /watchlists/{id}/`, which deletes
the whole list.

Every comma-joined query parameter goes through `comma_list`. A bare string is refused,
because iterating it would send one id per character. Items are de-duplicated in order. An
empty list is refused, because the server answers it with a 400 or a 500. Items must be
non-blank strings without commas, and `get_many` enforces the documented maximum of 50
epics.

### The pip scale comes from the prices endpoint

The pip scale is what turns pips into a price distance. Market details carry no pip data, so
`cc.markets.get(epic)` sends two reads:

1. `GET /markets/{epic}`;
2. `GET /prices/{epic}?max=1`, for `pipPosition` and `tickSize`.

If the second read answers `error.prices.not-found` (the market has no bars),
`Instrument.pip` stays `None`. `pip_size` and `pips_to_distance` then raise
`ValidationError`. Any other error is raised, including a 404 `error.not-found.epic`: a
downgrade there would hide a real failure behind a misleading "no price data". `get_many` makes
one request and leaves `pip` as `None`; its docstring says so. Market rows always carry
`pipPosition`, so `Market.pip` is required.

The pip size is `10 ** -pipPosition`: 0.01 for USDJPY and 0.0001 for EURUSD. A hard-coded
fifth decimal would be wrong for JPY pairs and for every non-FX market.

### Dealing rules are reported, not converted

`DealingRules` keeps each limit as `RuleValue(value, unit)`. On every demo market, sizes and
`minStepDistance` are in `POINTS` and the three stop and profit distances are in `PERCENTAGE`.
The price a percentage is taken of is not documented, so a conversion would be a guess
presented as a fact. Checking an order against the rules belongs to stage 2c, where orders
are defined.

### Silent drops become errors; empty answers stay empty

- `markets.get_many` and `sentiment.get_many` raise `NotFoundError` naming every requested
  id the server left out, and return the rest in request order. Without
  it, a caller looping over its epics would read a missing key as a server fault or skip the
  epic unnoticed. The status is 200 because the server answered 200, as in stage 2a.
- `prices.history` returns `()` for `error.prices.not-found`, because a window without bars
  is an empty answer. An unknown epic has its own code and still raises, so a typo is never
  hidden behind an empty tuple.
- A `prices.history` window without `limit` sends `max=1000`, the documented maximum.
  Without it the server stops at its default of 10 bars and a window comes back cut short
  with no sign of it. A window holding more than 1000 bars is still cut, as the docstring
  says, so a long range is read in several calls.
- A partial watchlist create returns `WatchlistCreation(watchlist_id, all_epics_added=False)`.
  An exception would lose the id of a list that already exists.
- `create` refuses a name outside 1..20 characters before sending. Watchlist changes require
  `status == "SUCCESS"`; any other answer raises `ApiError`.

### Read models

The read models follow ADR 0008:

- frozen dataclasses with `raw`;
- strict converters;
- server enumerations kept as `str`, among them `instrumentType` (which includes `UNKNOWN`)
  and `marketStatus`.

Fields absent on some demo markets are `Decimal | None`. Fields present on all 4011 are
required. Only `updateTimeUTC` and `snapshotTimeUTC` become `datetime`. The local
`updateTime` and `snapshotTime` stay in `raw`.

`Resolution` is an enum, because the documented set of bar lengths is closed.

## Observations (demo, filled in from the first contract run of stage 2b)

| Question | Observed | Pinned by |
|---|---|---|
| Do all market rows parse, including quote-less ones? | pending | `test_all_markets_parse` |
| Does navigation reach a leaf with markets? | pending | `test_navigation_reaches_markets` |
| Pip size of USDJPY and EURUSD on rows and through `get()` | pending | `test_pip_scale_of_fx_pairs` |
| Do details of every instrument type parse? | pending | `test_details_of_assorted_markets_parse` |
| Is an unknown epic in `get_many` named? | pending | `test_get_many_names_unknown_epics` |
| Empty window vs unknown epic on `/prices` | pending | `test_recent_prices` |
| Sentiment sums to 100 and batches by epic | pending | `test_sentiment` |
| Partial create, add, remove, delete of a watchlist | pending | `test_watchlist_round_trip` |

## Consequences

- `cc.markets.get` costs two requests. Callers who need details of many markets and no pip
  scale use `get_many`.
- A value that would change the meaning of a URL fails locally with `ValidationError`.
- If Capital.com starts adding pip data to details, or stops dropping unknown epics, the
  contract tests show it. Change the resource together with this ADR.
