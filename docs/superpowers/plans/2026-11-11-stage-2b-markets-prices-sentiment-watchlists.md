# Stage 2b — Markets, Prices, Sentiment, Watchlists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `cc.markets`, `cc.prices`, `cc.sentiment` and `cc.watchlists` on top of the 2a interfaces.

**Architecture:** This plan follows the 2a pattern:
- Read models are frozen, slotted dataclasses in `domain/`, built by `from_api` with the `domain/parsing.py` converters.
- Resources in `api/` take the `Core` and `.unwrap()`.
- Request rules (path segments, comma lists, documented limits) are pure functions, and they raise `ValidationError` before anything is sent.

**Tech Stack:** Python ≥3.11 and `requests`. Tests use pytest, `responses`, and `tests/unit/api/test_facade.py` (`DEMO`, `TOKENS`, `calls`).

**Spec:** `docs/superpowers/specs/2026-11-11-capitalcom-v2-design.md` (§2.1 Markets/Watchlists, §6.1, §6.2, §9 stage 2). ADR 0008 holds the read-model rules.

## Facts this plan relies on

Sources: the OpenAPI JSON embedded in https://open-api.capital.com/ (re-read on 2026-11-11), and four demo probe runs on 2026-11-11 (workflow_dispatch on a throwaway branch, since deleted).

- **`GET /markets?epics=A,B`** answers `{"marketDetails": [<GET /markets/{epic} shape>]}` (undocumented; the docs claim `markets`), in request order with duplicates collapsed. Unknown or wrong-case epics are silently dropped (one unknown epic gives 200 and `[]`). More than 50 gives 400 `error.too-many.epics`; empty gives 400 `error.null.epic`.
- **Market rows** (`GET /markets` with no params = 4011 rows; search; navigation leaves; watchlist markets) share one shape.
  - Always present: `epic`, `symbol`, `instrumentName`, `instrumentType` (including `UNKNOWN`), `marketStatus` (`TRADEABLE`/`CLOSED`), `lotSize`, `pipPosition` (int 0–7), `tickSize`, `scalingFactor`.
  - Sometimes absent, never `null`: `bid`/`offer`/`percentageChange` (3 rows), `high`/`low`/`netChange` (80), `updateTimeUTC` (1). Empty `searchTerm` gives 400 `error.null.searchTerm`; no hit gives `{"markets": []}`.
- **`GET /markets/{epic}`** has `instrument`, `dealingRules` and `snapshot`, but **no `pipPosition`/`tickSize`** (EURUSD, USDJPY, BTCUSD, AAPL). `snapshot.updateTime` is local, with no UTC twin. Sizes and `minStepDistance` are `POINTS`; the three stop/profit distances are `PERCENTAGE`.
- **`GET /prices/{epic}`** answers `{prices, instrumentType, pipPosition, tickSize}`; `max=1` returns the latest bar even on a closed market. `pipPosition`: EURUSD 4, USDJPY 2. A window with no bars gives 404 `error.prices.not-found`; `max` 0/1001 gives 400 `error.invalid.max`; `from > to` gives 400 `error.invalid.daterange`.
- **Navigation:** a category answers `{"nodes": [...]}`; a leaf `{"nodes": [], "markets": [...]}`. `limit` 501 gives 400 `error.invalid.limit`.
- **Sentiment:** the market id is the epic. One unknown id in a batch gives 404 `error.not-found.epic` for the whole call; empty `marketIds=` gives **500** `FIELD_VALIDATION_ERROR`.
- **Watchlists:** create with one bogus epic gives 200 `SUCCESS_NOT_ALL_INSTRUMENTS_ADDED` (only the valid epic is kept); a 21-char name gives 400 `error.size.createwatchlistrequest.name`. PUT of a present epic gives `SUCCESS`, of a bogus one 404. DELETE of an absent epic gives 404 `error.not-found.epic`; GET of an unknown id 404 `error.invalid.watchlist`; a second DELETE 404 `error.not-found.watchlist`.

## Rulings taken while planning

- **Pip data:**
  - `markets.get(epic)` sends `GET /markets/{epic}`, then `GET /prices/{epic}?max=1` for `pipPosition` and `tickSize`. Both are reads.
  - A `NotFoundError` from the second call leaves `Instrument.pip = None`, and `pip_size`/`pips_to_distance` then raise. Any other error propagates.
  - `get_many` makes one request and leaves `pip = None` (its docstring says so).
  - *Why:* spec §6.2 puts pip behaviour on `Instrument`, and details carry no pip. Cost if wrong: one extra GET per `get()`.
- **`DealingRules`:**
  - Keeps `RuleValue(value, unit: str)` and converts nothing, because the reference price for `PERCENTAGE` is undocumented.
  - `DealingRules.validate(order)` (spec §6.2) moves to 2c, where `OrderRequest`, its only input, is defined.
- **`get_many` with missing epics:** raises `NotFoundError(200, None, "no market for epics: [...]")`. A silent drop would desync a caller's per-epic loop. This follows 2a's convention: status 200, because the server answered 200.
- **Empty price window:** raises `NotFoundError` (`error.prices.not-found`) and is not turned into `()`. An unknown epic may answer with the same code, and an empty tuple would hide a typo.
- **Partial watchlist create:** returns `WatchlistCreation(watchlist_id, all_epics_added=False)`. An exception would lose the id of a list that already exists.

## Global Constraints

- All 2a constraints apply: runtime dependency `requests` only; every tracked hand-written file ≤300 lines; imports inward only; no Claude attribution; money, prices, sizes and distances are `Decimal`; every model has `raw` (`repr=False`, `compare=False`); server enumerations stay `str`; only UTC fields become `datetime`; query datetimes must be aware.
- Every id or epic placed in a URL path goes through `path_segment`. Every comma-joined query goes through `comma_list`.
- Contract tests:
  - Demo only. The shared `demo_core` is used, and any state created is deleted in `finally`.
  - Watchlists are named with the prefix `cc-contract-`, and leftovers with that prefix are swept first.
- Commands use the repo venv: `pytest` means `.venv/Scripts/python.exe -m pytest`.
- Payload fixtures: copy the doc samples from `.superpowers/apidoc/openapi.json` (local, gitignored; re-extract with `.superpowers/tools/dump_openapi.py`). Trim them to the fields a test needs, and never copy account data.

## Review Focus

1. **A string where an iterable of ids is expected.** `get_many("EURUSD")` and `sentiment.get_many("BTCUSD")` must raise `ValidationError`, never send six one-letter epics. An empty iterable must raise too, never send `epics=` (400) or `marketIds=` (500). Pinned in Task 1.
2. **An empty or path-breaking segment.** `watchlists.remove_market(wid, "")` must not become `DELETE /watchlists/{wid}/`, which deletes the whole list. An epic like `"A/B"` must be percent-encoded, never re-routed. Pinned in Tasks 1 and 6.
3. **Unknown or lowercase epic in `get_many`.** The server drops it silently, so the client must raise `NotFoundError` naming it. Pinned in Task 3.
4. **A closed or quote-less market.** Rows lacking `bid`/`offer`/`high`/`low`/`updateTimeUTC` must parse with `None`, so `markets.all()` never fails on one odd row. Pinned in Task 2, and by the all-markets contract test in Task 7.
5. **Pip size of JPY pairs.** USDJPY must give `pip_size == Decimal("0.01")`, EURUSD `Decimal("0.0001")`, with no hard-coded 5. Pinned in Tasks 2, 3 and 7.

---

### Task 1: Request values and `Resolution`

**Files:** Create `src/capitalcom/domain/request_values.py`. Modify `src/capitalcom/domain/enums.py`. Test: `tests/unit/domain/test_request_values.py`.

**Interfaces (Produces):**
- `path_segment(value: object, field: str) -> str`:
  - A non-`str`, or a value that is empty after `strip()`, raises `ValidationError(f"{field} must be a non-empty string")`.
  - Otherwise it returns `urllib.parse.quote(value, safe="")`.
- `comma_list(values: Iterable[str], field: str, *, max_items: int | None) -> str`:
  - A `str` raises `ValidationError(f"{field} must be an iterable of strings, not a string")`.
  - Items are de-duplicated, keeping order.
  - An empty result, a non-`str` item, a blank item, or an item containing `,` raises.
  - More than `max_items` items after de-duplication raises.
  - Otherwise it returns the items joined with `","`.
- `Resolution(StrEnum)`: `MINUTE`, `MINUTE_5`, `MINUTE_15`, `MINUTE_30`, `HOUR`, `HOUR_4`, `DAY`, `WEEK` (the documented closed set).

- [ ] **Step 1: Write the failing tests:**
  - `path_segment("A/B?#", "epic") == "A%2FB%3F%23"`.
  - `path_segment("", "epic")`, `path_segment("  ", "epic")` and `path_segment(None, "epic")` raise `ValidationError`.
  - `comma_list(["A", "B", "A"], "epics", max_items=50) == "A,B"`.
  - `comma_list("AB", "epics", max_items=50)` raises, and the message contains `"not a string"`.
  - `comma_list([], ...)`, `[""]`, `["A,B"]` and `[1]` raise.
  - `comma_list([f"E{i}" for i in range(51)], "epics", max_items=50)` raises.
  - `Resolution("HOUR_4") is Resolution.HOUR_4`.
- [ ] **Step 2: Run** `pytest tests/unit/domain/test_request_values.py -q`. Expected: FAIL with ImportError.
- [ ] **Step 3: Implement** both functions and the enum.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(domain): add path-segment and comma-list request rules, Resolution`.

### Task 2: Market read models

**Files:**
- Create `src/capitalcom/domain/market_details.py`, holding `PipScale`, `RuleValue`, `DealingRules`, `Instrument`, `MarketSnapshot` and `MarketDetails`.
- Create `src/capitalcom/domain/markets.py`, holding `Market`, `MarketNode` and `NodeContents`.
- Tests: `tests/unit/domain/test_market_details.py`, `tests/unit/domain/test_markets.py`.

**Interfaces (Produces).** All are frozen, slotted dataclasses with `raw` where they are built from a payload.
- **`PipScale(position: int, tick_size: Decimal)`:**
  - `from_api(payload)` reads `pipPosition` (`require_int`) and `tickSize` (`require_decimal`).
  - `size -> Decimal` is `Decimal(1).scaleb(-position)`.
  - `to_distance(pips: Decimal | int) -> Decimal` is `pips * size`. A `bool`, a non-number or a non-finite value raises `ValidationError`.
- **`RuleValue(value: Decimal, unit: str)`:** `from_api(payload, field)`.
- **`DealingRules`:**
  - Required: `min_step_distance`, `min_deal_size`, `max_deal_size`, `min_size_increment` (`RuleValue`).
  - Optional (`RuleValue | None`): `min_guaranteed_stop_distance`, `min_stop_or_profit_distance`, `max_stop_or_profit_distance`.
  - Optional (`str | None`): `market_order_preference`, `trailing_stops_preference`.
  - Plus `raw`.
- **`Instrument`:**
  - Fields: `epic`, `symbol`, `name`, `type`, `currency` (str); `lot_size`, `margin_factor` (Decimal); `margin_factor_unit` (str); `guaranteed_stop_allowed` (bool); `pip: PipScale | None`; `raw`.
  - `from_api(payload, pip: PipScale | None)`.
  - `pip_size -> Decimal` and `pips_to_distance(pips) -> Decimal` raise `ValidationError("pip scale unknown for <epic>: use cc.markets.get(epic)")` when `pip is None`.
  - `lots_to_size(lots: Decimal | int) -> Decimal` is `lots * lot_size`. It uses the same number check as `to_distance`.
- **`MarketSnapshot`:**
  - Fields: `market_status` (str); `bid`, `offer`, `high`, `low`, `net_change`, `percentage_change` (`Decimal | None`); `decimal_places_factor`, `scaling_factor` (int); `raw`.
  - `updateTime` stays in `raw`.
- **`MarketDetails(instrument, dealing_rules, snapshot, raw)`:** `from_api(payload, pip: PipScale | None = None)`.
- **`Market`:**
  - Fields: `epic`, `symbol`, `instrument_name`, `instrument_type`, `market_status` (str); `lot_size` (Decimal); `pip: PipScale` (required); `bid`, `offer`, `high`, `low` (`Decimal | None`); `update_time_utc: datetime | None`; `raw`.
  - `pips_to_distance` delegates to `pip`.
- **`MarketNode(node_id: str, name: str)`** reads `id` and `name`. **`NodeContents(nodes: tuple[MarketNode, ...], markets: tuple[Market, ...])`:** `from_api` treats a missing `markets` key as `()`.

- [ ] **Step 1: Write the failing tests.** Use payloads copied from the Facts (Silver details sample; USDJPY row with `pipPosition` 2 and `tickSize` 0.001):
  - `PipScale(2, Decimal("0.001")).size == Decimal("0.01")` and `PipScale(4, ...).to_distance(10) == Decimal("0.0010")`.
  - `to_distance(True)` and `to_distance(Decimal("NaN"))` raise.
  - `MarketDetails.from_api(silver)`:
    - `instrument.pip is None`, and `instrument.pip_size` raises `ValidationError`;
    - `dealing_rules.max_stop_or_profit_distance == RuleValue(Decimal(60), "PERCENTAGE")`.
  - Removing `minGuaranteedStopDistance` gives `None`. Removing `minDealSize` raises `ResponseFormatError` naming `minDealSize`.
  - `Instrument.lots_to_size(Decimal("2.5"))` with `lotSize` 1 gives `Decimal("2.5")`.
  - `Market.from_api(row)` without `bid`, `high` and `updateTimeUTC` parses with `None`s. Without `pipPosition` it raises.
  - `NodeContents.from_api({"nodes": [...]})` gives `markets == ()`.
- [ ] **Step 2: Run** `pytest tests/unit/domain/test_market_details.py tests/unit/domain/test_markets.py -q`. Expected: FAIL with ImportError.
- [ ] **Step 3: Implement.** If no existing helper fits, add `optional_mapping(payload, key)` to `parsing.py` for the optional `RuleValue` fields, with its own test in `tests/unit/domain/test_parsing.py`.
- [ ] **Step 4: Run** the same command plus `tests/unit/domain/test_parsing.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(domain): add market, instrument and dealing-rule read models`.

### Task 3: `cc.markets`

**Files:** Create `src/capitalcom/api/markets.py`. Modify `src/capitalcom/api/client.py` (`self.markets`). Test: `tests/unit/api/test_markets.py`. Use the 2a `api` fixture pattern from `tests/unit/api/test_accounts.py`.

**Interfaces.**
- Consumes Tasks 1–2.
- Produces `MarketsResource(core)` with these methods:
  - `navigation() -> tuple[MarketNode, ...]` (`GET /api/v1/marketnavigation`).
  - `browse(node_id: str, *, limit: int | None = None) -> NodeContents`. `limit` must be an int (not bool) in 1..500.
  - `search(term: str) -> tuple[Market, ...]` (`params={"searchTerm": term}`). A blank term raises `ValidationError`.
  - `all() -> tuple[Market, ...]` (no params; the docstring says it returns about 4000 rows).
  - `get(epic: str) -> MarketDetails`. It sends two GETs (see Rulings) and passes `PipScale.from_api(prices_body)` into `MarketDetails.from_api`.
  - `get_many(epics: Iterable[str]) -> Mapping[str, MarketDetails]`:
    - It sends `params={"epics": comma_list(epics, "epics", max_items=50)}` and reads `marketDetails`.
    - The result is keyed by `instrument.epic`, in request order.
    - Requested epics missing from the answer raise `NotFoundError(200, None, f"no market for epics: {missing}")`.

- [ ] **Step 1: Write the failing tests:**
  - `browse("a/b", limit=2)` calls `/api/v1/marketnavigation/a%2Fb?limit=2`. Both `limit=0` and `limit=501` raise and send nothing.
  - `search(" ")` raises and sends nothing.
  - `get("USDJPY")`:
    - with `/prices/USDJPY` answering `pipPosition` 2, it gives `instrument.pip_size == Decimal("0.01")`, and the second call has `max=1`;
    - with the prices call answering 404, it gives `instrument.pip is None`;
    - with the prices call answering 400, it raises `ApiError`.
  - `get_many(["USDJPY", "EURUSD"])` given `marketDetails` for both gives keys `["USDJPY", "EURUSD"]`.
  - `get_many(["BTCUSD", "eurusd"])` given only BTCUSD raises `NotFoundError` whose message contains `eurusd`.
  - `get_many("EURUSD")` and `get_many([])` raise `ValidationError` and send nothing.
- [ ] **Step 2: Run** `pytest tests/unit/api/test_markets.py -q`. Expected: FAIL with ImportError.
- [ ] **Step 3: Implement** the resource and wire `self.markets`.
- [ ] **Step 4: Run** `pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): add markets namespace`.

### Task 4: `cc.prices`

**Files:** Create `src/capitalcom/domain/prices.py` and `src/capitalcom/api/prices.py`. Modify `api/client.py`. Tests: `tests/unit/domain/test_prices.py`, `tests/unit/api/test_prices.py`.

**Interfaces (Produces):**
- `BidAsk(bid: Decimal, ask: Decimal)`. Both are required.
- `PriceBar`:
  - Fields: `time: datetime` (from `snapshotTimeUTC`, required); `open`, `close`, `high`, `low: BidAsk` (from `openPrice` etc.); `volume: Decimal` (`lastTradedVolume`); `raw`.
  - `snapshotTime` (local) stays in `raw`.
- `price_params(resolution: Resolution | str | None, limit: int | None, start: datetime | None, end: datetime | None) -> dict[str, str]`:
  - An unknown resolution raises `ValidationError`, and so does a `limit` that is not an int in 1..1000 (bool excluded).
  - A naive datetime raises (via `to_api_time`), and so does `start > end`.
  - The keys are `resolution`, `max`, `from` and `to`, each only when given.
- `PricesResource(core).history(epic: str, resolution: Resolution | None = None, *, limit: int | None = None, start: datetime | None = None, end: datetime | None = None) -> tuple[PriceBar, ...]`:
  - It calls `GET /api/v1/prices/{path_segment(epic)}`.
  - The docstring says a window with no bars raises `NotFoundError` (`error.prices.not-found`).

- [ ] **Step 1: Write the failing tests:**
  - `PriceBar.from_api(first_bar_of_doc_sample)` gives `time == datetime(2022, 4, 6, 13, 18, tzinfo=UTC)` and `open.bid == Decimal("24.356")`.
  - `price_params("HOUR_4", 5, aware_start, aware_end)` gives `{"resolution": "HOUR_4", "max": "5", "from": "...", "to": "..."}`.
  - `limit=0`, `limit=1001`, `limit=True`, `resolution="HOURLY"`, a naive start, and `start > end` each raise.
  - `history("BTCUSD", Resolution.MINUTE, limit=3)` sends `resolution=MINUTE&max=3` and returns 3 bars.
  - A 404 body `{"errorCode": "error.prices.not-found"}` raises `NotFoundError` with that `error_code`.
- [ ] **Step 2: Run** `pytest tests/unit/domain/test_prices.py tests/unit/api/test_prices.py -q`. Expected: FAIL with ImportError.
- [ ] **Step 3: Implement** and wire `self.prices`.
- [ ] **Step 4: Run** `pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): add prices namespace`.

### Task 5: `cc.sentiment`

**Files:** Create `src/capitalcom/domain/sentiment.py` and `src/capitalcom/api/sentiment.py`. Modify `api/client.py`. Test: `tests/unit/api/test_sentiment.py`.

**Interfaces (Produces):**
- `Sentiment(market_id: str, long_percentage: Decimal, short_percentage: Decimal, raw)`, read from `marketId`, `longPositionPercentage` and `shortPositionPercentage`.
- `SentimentResource(core)`:
  - `get(market_id) -> Sentiment` calls `/api/v1/clientsentiment/{path_segment}`.
  - `get_many(market_ids: Iterable[str]) -> Mapping[str, Sentiment]`:
    - It sends `marketIds=comma_list(..., max_items=None)` and reads `clientSentiments`, keyed by `market_id`.
    - The docstring says one unknown id fails the whole call with `NotFoundError`.

- [ ] **Step 1: Write the failing tests:**
  - `get("BTCUSD").long_percentage == Decimal("86.58")`.
  - `get_many(["SILVER", "NATURALGAS"])` with the doc sample gives keys in that order.
  - `get_many([])` and `get_many("SILVER")` raise and send nothing (the server answers 500).
  - `get("")` raises.
- [ ] **Step 2: Run** `pytest tests/unit/api/test_sentiment.py -q`. Expected: FAIL with ImportError.
- [ ] **Step 3: Implement** and wire `self.sentiment`.
- [ ] **Step 4: Run** `pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): add client sentiment namespace`.

### Task 6: `cc.watchlists`

**Files:** Create `src/capitalcom/domain/watchlist.py` and `src/capitalcom/api/watchlists.py`. Modify `api/client.py`. Test: `tests/unit/api/test_watchlists.py`.

**Interfaces (Produces):**
- `Watchlist(watchlist_id: str, name: str, editable: bool, deleteable: bool, default_system: bool, raw)`, read from `id`, `name`, `editable`, `deleteable` and `defaultSystemWatchlist`.
- `WatchlistCreation(watchlist_id: str, all_epics_added: bool)`.
- `MAX_NAME_LENGTH = 20`.
- `WatchlistsResource(core)`:
  - `list() -> tuple[Watchlist, ...]`.
  - `create(name: str, epics: Iterable[str] = ()) -> WatchlistCreation`:
    - The name must be a `str` of length 1..20.
    - `epics` goes through `comma_list` rules, but is sent as a JSON list. An empty iterable sends no `epics` key.
    - `SUCCESS` gives True. `SUCCESS_NOT_ALL_INSTRUMENTS_ADDED` gives False. Any other status raises `ApiError(200, None, ...)`.
  - `get(watchlist_id) -> tuple[Market, ...]`.
  - `add_market(watchlist_id, epic) -> None` (PUT `{"epic": epic}`).
  - `remove_market(watchlist_id, epic) -> None`.
  - `delete(watchlist_id) -> None`.
  - The last three require `status == "SUCCESS"`, or they raise `ApiError(200, None, ...)`.

- [ ] **Step 1: Write the failing tests:**
  - `create("x" * 21)` and `create("")` raise and send nothing.
  - `create("Lorem", ["SILVER", "NOSUCH"])` answered `SUCCESS_NOT_ALL_INSTRUMENTS_ADDED` gives `WatchlistCreation("123459", False)`. The sent body is `{"name": "Lorem", "epics": ["SILVER", "NOSUCH"]}`.
  - A status of `"FAILED"` raises `ApiError`.
  - `remove_market("123", "")` raises and sends nothing.
  - `remove_market("1 2", "A/B")` calls `/api/v1/watchlists/1%202/A%2FB`.
  - `get("123")` with the doc sample gives two `Market`s, with `pip.position` values 2 and 3.
- [ ] **Step 2: Run** `pytest tests/unit/api/test_watchlists.py -q`. Expected: FAIL with ImportError.
- [ ] **Step 3: Implement** and wire `self.watchlists`.
- [ ] **Step 4: Run** `pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): add watchlists namespace`.

### Task 7: Exports, contract tests, ADR 0009

**Files:**
- Modify `src/capitalcom/__init__.py` and `tests/unit/api/test_facade.py::test_public_exports`.
- Create `tests/contract/test_markets_contract.py` and `tests/contract/test_watchlists_sentiment_contract.py`.
- Create `docs/adr/0009-market-data.md`.

- [ ] **Step 1: Write the failing export test.** Extend `test_public_exports` to cover `Market`, `MarketNode`, `NodeContents`, `MarketDetails`, `Instrument`, `DealingRules`, `RuleValue`, `MarketSnapshot`, `PipScale`, `Resolution`, `PriceBar`, `BidAsk`, `Sentiment`, `Watchlist` and `WatchlistCreation`. Run it: FAIL. Add the exports. Run: PASS.
- [ ] **Step 2: Write the contract tests.** They use demo only, log types and counts only, and never log account data.
  - `test_all_markets_parse`: `cc.markets.all()` gives more than 1000 rows.
  - `test_navigation_reaches_markets`: descend at most 4 levels from the first top node to a node with markets.
  - `test_pip_scale_of_fx_pairs`:
    - `search("USDJPY")` holds USDJPY with `pip.size == Decimal("0.01")`, and `search("EURUSD")` holds EURUSD with `pip.size == Decimal("0.0001")`;
    - `markets.get("USDJPY").instrument.pip_size == Decimal("0.01")`.
  - `test_details_of_assorted_markets_parse`: `get_many` of up to 50 epics, sampled across every `instrument_type` of `all()`, gives keys equal to the request.
  - `test_get_many_names_unknown_epics`: `get_many(["BTCUSD", "NOSUCHEPIC999"])` raises `NotFoundError`.
  - `test_recent_prices`:
    - `history("BTCUSD", Resolution.MINUTE, limit=5)` gives 1..5 bars with ascending `time`;
    - a window in 2001 raises `NotFoundError` with `error_code == "error.prices.not-found"`.
  - `test_sentiment`: `get("BTCUSD")` long + short is within `Decimal("0.02")` of 100, and `get_many(["BTCUSD", "EURUSD"])` has both keys.
  - `test_watchlist_round_trip`:
    - sweep `cc-contract-` leftovers;
    - `create(f"cc-contract-{token_hex(3)}", ["BTCUSD", "NOSUCHEPIC999"])` gives `all_epics_added is False`;
    - `get` holds only BTCUSD;
    - `add_market` ETHUSD, then `remove_market` ETHUSD;
    - `delete` in `finally`;
    - `get` after the delete raises `NotFoundError`.
- [ ] **Step 3: Write the ADR.** Record the Facts and the Rulings above, in the 2a ADR style. Include an Observations table, filled in after the first CI run on PR #4.
- [ ] **Step 4: Run the gates:**
  - `ruff check .`, `ruff format --check .` and `mypy`;
  - `pytest -q`, which needs coverage ≥95;
  - the 300-line check;
  - local Semgrep: `PYTHONUTF8=1 .superpowers/semgrep-venv/Scripts/semgrep scan --config p/python --config p/security-audit --config p/secrets --severity ERROR --error`.

  Expected: all green, 0 blocking findings.
- [ ] **Step 5: Commit** `feat: export stage 2b models, add contract tests and ADR 0009`.
- [ ] **Step 6: Final review.** Run `/code-review high` over `master...HEAD` (2b commits only), re-grade the findings, then do one fix pass with RED→GREEN tests per the executing-plans skill.
- [ ] **Step 7: Push** to `rewrite/stage-2-rest` (PR #4 stays a draft). Read the contract job's log, fill in the ADR Observations table, and commit `docs(adr): record stage 2b contract observations`.
- [ ] **Step 8: Hand over.** Update the stage status in the owner's notes. The next plan is 2c (positions, orders, `DealingRules.validate`).
