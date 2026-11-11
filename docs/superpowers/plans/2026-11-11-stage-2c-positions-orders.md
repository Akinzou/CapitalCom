# Stage 2c — Positions and Working Orders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `cc.positions` and `cc.orders` (open, read, amend, close/cancel, all confirmed), opt-in pre-trade size validation, and fold the duplications deferred from 2b.

**Architecture:** This plan follows 2a and 2b:
- Request values (`StopLoss`, `TakeProfit`, `OrderRequest`, `WorkingOrderRequest`) are frozen dataclasses that reject an invalid state in `__post_init__`.
- Read models live in `domain/` and are built by `from_api`.
- Resources in `api/` submit a request, then wait on `core.confirmer` and `.unwrap()`.

**Tech Stack:** Python ≥3.11 and `requests`. Tests use pytest, `responses`, and `tests/unit/api/test_facade.py` (`DEMO`, `TOKENS`).

**Spec:** `docs/superpowers/specs/2026-11-11-capitalcom-v2-design.md` (§2.4, §6.1, §6.2, §6.4, §9 stage 2). Also ADR 0007 (position id, partial close) and ADR 0009 (dealing rules).

## Facts this plan relies on

Sources: the OpenAPI JSON in `.superpowers/apidoc/openapi.json`, and one demo probe run on 2026-11-11 (workflow_dispatch on a throwaway branch, since deleted; log in `.superpowers/probe-2c.log`). All facts were seen on BTCUSD BUY, on a CFD account with hedging off.

- **PUT replaces all protection; it does not merge.** `PUT /positions/{id}` with only `profitLevel` removed the stop, with only `stopDistance` removed the take-profit, and `{}` removed both. `PUT /workingorders/{id}` with only `level` dropped `goodTillDate` (`timeInForce` became `GOOD_TILL_CANCELLED`) and the stop distance; omitting `level` kept the level.
- **Confirmations** (`status` → `affectedDeals` statuses):
  - open position `OPEN` → `[OPENED]` (the position id; top-level `dealId` differs, ADR 0007); amend `AMENDED` → `[AMENDED]` (`dealId` is the position id); close `CLOSED` → `[FULLY_CLOSED]`;
  - create order `OPEN` → `[OPENED]` (`dealId` equals it; both are the id in `GET /workingorders`); amend `AMENDED` (same id kept); cancel `DELETED` → `[DELETED]`;
  - rejected: `dealStatus` `REJECTED`, `status` `DELETED`, no affected deals, reason under `rejectReason` (`RC_NOT_ENOUGH_MARGIN`).
- **The server silently rounds the size:** an open of 0.00015 (increment 0.0001) was accepted and booked as 0.00010.
- **All 4011 demo markets:** size rules in `POINTS`, stop/profit distance rules in `PERCENTAGE`; every `minDealSize` lies on its `minSizeIncrement` grid; `trailingStopsPreference` is `NOT_AVAILABLE` everywhere. The account type is `CFD` only.
- **Distance limits are checked on the resulting level against the live quote:** a take-profit 150% away was accepted although `maxStopOrProfitDistance` is 100%; a stop just under the bid gave 400 `error.invalid.stoploss.maxvalue: 74490.85` (the code carries the limit price). Inferred, not proven: a distance counts from the position's open level.
- **Server 400s:** `error.conflict.stoploss.types` (stop level with stop distance), `error.null.stoploss.value` (guaranteed, no stop), `error.null.stopDistance.value` (trailing, no distance), `error.invalid.size.maxvalue`, `error.validation.stop.price` (STOP order on the wrong side), `error.not-in-future.goodTillDate`, `error.invalid.dealId` (malformed id). A closed position gives 404 `error.not-found.dealId` (ADR 0007).
- **Rows:** `GET /positions[/{id}]` gives `{position, market}`, whose `market` row has `pipPosition` and `tickSize`; `stopLevel`, `profitLevel` and `trailingStop` are absent when unset, and a stop set by distance or amount is listed as `stopLevel`. `GET /workingorders` gives `{workingOrderData, marketData}` without `pipPosition`; an order's `stopDistance` is listed signed (sent 3724.38, listed −3724.38); `goodTillDateUTC` equals what was sent.

## Rulings taken while planning (for the owner to accept)

1. **`amend` takes the whole protection state.** `positions.amend(position_id, *, stop, profit)` and `orders.amend(order_id, *, good_till, stop, profit, level=None)` have required keyword arguments with no default: leaving one out is a `TypeError`, and `None` means "remove". *Why:* the server replaces everything, so a merge-style `amend(profit=...)` would silently delete the stop. *Rejected:* read-merge-write, which costs a hidden GET and relies on row shapes the probe did not cover (trailing or guaranteed stops, SELL, re-sent order distances). Required arguments can later become optional-with-keep without breaking callers.
2. **Spec §6.1 example** becomes `cc.positions.amend(deal.position_id, stop=None, profit=TakeProfit(level=...))`: `deal.deal_id` is not the position (ADR 0007), and stops are value objects (`StopLoss`, `TakeProfit`) instead of eight flat keyword arguments, so combinations the server refuses cannot be built.
3. **`validate` checks sizes only** (spec §6.2 lists distances too): `MarketDetails.validate(order)` checks the epic, then `DealingRules.validate(order)` checks min, max and increment. Distances are left to the server, which judges the resulting level against the live quote; a local check would have refused the accepted 150% take-profit. A rule in an unexpected unit raises `ValidationError` instead of being skipped.
4. **Rounded sizes raise** `SizeAdjustedError(requested, confirmation)` (in `domain/confirmation.py`) after every open or create. The deal already exists, so the error carries the confirmation and its `position_id`. Observed on BTCUSD BUY only; netting (hedging off: an opposite open closes instead) is pinned by `test_netting_open` in Task 7. Cost if wrong: an open on an unobserved path raises after the deal is booked, though the error still carries the confirmation.
5. **The "real stocks" rule (spec §6.2) is deferred:** the demo has only a CFD account, so it cannot be observed; the server stays authoritative (ADR 0010).
6. **Error codes stay verbatim:** `error_code` keeps the `: 74490.85` suffix; splitting it would guess a format.
7. **Position id:** `DealConfirmation.position_id` is the first affected deal with status `OPENED`, else `None` (netting). For a created order it is the order id, as is `deal_id`.

## Global Constraints

- All 2a and 2b constraints apply: dependency `requests` only; files ≤300 lines; imports point inward; no Claude attribution; money, prices, sizes and distances are `Decimal`; models are frozen and slotted, with `raw` (`repr=False`, `compare=False`); server enumerations stay `str`; only UTC fields become `datetime`.
- Every id in a URL path goes through `domain.request_values.path_segment`, not `application.json_codec.path_segment`.
- Caller numbers go through `caller_quantity`, which refuses `bool`, `float` and non-finite values. Sizes, levels, distances and amounts must also be `> 0`.
- Contract tests: demo only, sharing `demo_core`; BTCUSD at minimum size; working orders at 50% of the bid or less, so they cannot fill; positions and orders swept against a snapshot taken before the test; no deal or account ids in logs.
- `pytest` means `.venv/Scripts/python.exe -m pytest -p no:cacheprovider`.

## Review Focus

1. **An empty, blank or `..` id** must never reach `DELETE /api/v1/positions/` or `/workingorders/`, which would hit a parent path. Pinned in Tasks 5 and 6.
2. **An amend that loses protection.** Leaving out `stop`, `profit` or `good_till` must be a `TypeError`. Only explicit `None` sends no key. Pinned in Tasks 5 and 6.
3. **A size rounded by the server** must raise `SizeAdjustedError` with the position id reachable, never return as if the requested size were booked. Pinned in Tasks 3 and 5.
4. **`True`, `0.1` (float), `Decimal("NaN")`, `0` or `-1`** as a size, level, distance or amount must raise `ValidationError` before anything is sent. Pinned in Task 2.
5. **A naive `good_till`** must raise; an aware non-UTC one must be sent as UTC. Pinned in Tasks 2 and 6.

---

### Task 1: Fold the duplications deferred from 2b

**Files:**
- Modify:
  - `domain/request_values.py`, `domain/market_details.py`, `domain/api_time.py`, `domain/history.py`, `domain/prices.py`, `domain/parsing.py`, `domain/watchlist.py`;
  - `api/markets.py`, `api/accounts.py`, `api/watchlists.py`, `api/sentiment.py`.
- Tests: the matching `tests/unit/domain/*` and `tests/unit/api/*` files.

**Interfaces (Produces):**
- **In `request_values`:**
  - `caller_quantity(value: object, field: str) -> Decimal`, moved from `market_details` with its behaviour unchanged.
  - `bounded_int(value: object, field: str, low: int, high: int) -> int` raises `ValidationError(f"{field} must be an int within {low}..{high}, got {value!r}")` for a `bool`, a non-`int` or a value out of range.
  - `comma_list(...) -> tuple[str, ...]`; callers join with `","` where they send it.
- **`window_params(start: datetime | None, end: datetime | None) -> dict[str, str]`** in `api_time`:
  - `from`/`to` via `to_api_time`;
  - `start > end` raises `ValidationError(f"start {start} is after end {end}")`;
  - `history_params` and `price_params` call it.
- **`check_success(answer: object, what: str) -> None`** in `parsing` raises `ApiError(200, None, f"{what}: {answer!r}")` unless `answer` is a mapping with `status == "SUCCESS"`. It is used by `update_preferences` and `watchlists`.
- **`check_name`** also refuses a name that is blank after `strip()`.
- `top_up` uses `caller_quantity`. `browse` and `price_params` use `bounded_int`.

- [ ] **Step 1: Write the failing tests:**
  - `bounded_int(5, "limit", 1, 500) == 5`; `True`, `"5"`, `0` and `501` raise with `"limit"`.
  - `comma_list(["A", "B", "A"], "epics", max_items=50) == ("A", "B")`.
  - `window_params(t1, t0)` raises; `window_params(None, t0) == {"to": ...}`.
  - `check_success({"status": "SUCCESS"}, "x")` returns `None`; `{"status": "FAIL"}` and `None` raise `ApiError`.
  - `check_name("   ")` raises.
  - `caller_quantity` is importable from `request_values`.
- [ ] **Step 2: Run** `pytest tests/unit -q`. Expected: FAIL (ImportError and the new assertions).
- [ ] **Step 3: Implement** them and switch every caller. Delete the old copies (grep proves no other caller, and the result goes in the commit). Existing tests may change only where this task changes them: error text, the `comma_list` tuple, and the `caller_quantity` import.
- [ ] **Step 4: Run** `pytest -q`. Expected: PASS, coverage ≥95.
- [ ] **Step 5: Commit** `refactor(domain): share request and status checks across resources`. The body says: "one rule per check, because two copies drift and one of them then lets a bad value through".

### Task 2: Protection and order requests

**Files:**
- Create `src/capitalcom/domain/protection.py` and `src/capitalcom/domain/order_request.py`.
- Modify `domain/enums.py`.
- Tests: `tests/unit/domain/test_protection.py`, `tests/unit/domain/test_order_request.py`.

**Interfaces (Produces):**
- **`OrderType(StrEnum)`:** `LIMIT`, `STOP`.
- **`StopLoss(level=None, distance=None, amount=None, guaranteed: bool = False, trailing: bool = False)`:**
  - Exactly one of `level`, `distance` or `amount`, each through `caller_quantity` and `> 0`.
  - `guaranteed` and `trailing` cannot both be set; `trailing` needs `distance`.
  - `to_body() -> dict[str, Any]` writes `stopLevel`, `stopDistance` or `stopAmount`, plus `guaranteedStop: True` / `trailingStop: True` only when set.
- **`TakeProfit(level=None, distance=None, amount=None)`:** exactly one, `> 0`. `to_body()` writes `profitLevel`, `profitDistance` or `profitAmount`.
- **`protection_body(stop: StopLoss | None, profit: TakeProfit | None) -> dict[str, Any]`:** merges both bodies; `{}` when both are `None`.
- **`OrderRequest(epic: str, direction: Direction | str, size: Decimal | int, stop: StopLoss | None = None, profit: TakeProfit | None = None)`:**
  - `epic` follows the `path_segment` rule.
  - `direction` goes through `Direction(...)`; an unknown value raises `ValidationError`.
  - `size` goes through `caller_quantity` and must be `> 0`; it is stored as `Decimal`.
  - `to_body()` gives `{"epic", "direction", "size"} | protection_body(...)`.
- **`WorkingOrderRequest(order: OrderRequest, level: Decimal | int, type: OrderType | str, good_till: datetime | None = None)`:**
  - `level` must be `> 0`.
  - `type` goes through `OrderType(...)`.
  - `good_till` is checked at construction with `to_api_time`.
  - `to_body()` gives `order.to_body() | {"level", "type"}`, plus `goodTillDate` when it is set.

- [ ] **Step 1: Write the failing tests:**
  - `StopLoss(distance=Decimal("5")).to_body() == {"stopDistance": Decimal("5")}`.
  - `StopLoss(level=1, guaranteed=True).to_body() == {"stopLevel": Decimal(1), "guaranteedStop": True}`.
  - `StopLoss()`, `StopLoss(level=1, distance=1)`, `StopLoss(distance=1, guaranteed=True, trailing=True)` and `StopLoss(level=1, trailing=True)` raise `ValidationError`.
  - `StopLoss(distance=x)` raises for each `x` in `True`, `0.1`, `Decimal("NaN")`, `0` and `-1`; so does `TakeProfit(amount=x)`.
  - `protection_body(None, None) == {}`.
  - `OrderRequest("BTCUSD", "BUY", Decimal("0.0001"), profit=TakeProfit(level=9)).to_body() == {"epic": "BTCUSD", "direction": "BUY", "size": Decimal("0.0001"), "profitLevel": Decimal(9)}`.
  - `OrderRequest("..", ...)`, `direction="HOLD"` and `size=0` raise.
  - `WorkingOrderRequest(order, 20, "LIMIT", datetime(2030, 1, 1, 2, tzinfo=timezone(timedelta(hours=2))))` has `to_body()["goodTillDate"] == "2030-01-01T00:00:00"`. A naive `good_till` and `type="MARKET"` raise.
- [ ] **Step 2: Run** `pytest tests/unit/domain/test_protection.py tests/unit/domain/test_order_request.py -q`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement.** Frozen, slotted dataclasses, normalised in `__post_init__` with `object.__setattr__`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(domain): add stop-loss, take-profit and order request values`.

### Task 3: Confirmation ids, size check and pre-trade validation

**Files:**
- Modify `domain/confirmation.py` and `domain/market_details.py`.
- Tests: `tests/unit/domain/test_confirmation.py`, `tests/unit/domain/test_market_details.py`.

**Interfaces (Produces):**
- **`DealConfirmation.position_id -> str | None`:** the first affected deal whose `status == "OPENED"`.
- **`SizeAdjustedError(CapitalComError)`** in `confirmation.py`:
  - `__init__(requested: Decimal, confirmation: DealConfirmation)`;
  - properties `requested` and `confirmation`;
  - the message names the reference, the requested size and the booked size;
  - it is picklable through `_init_args`.
- **`DealConfirmation.require_size(requested: Decimal) -> DealConfirmation`** returns `self` when `self.size == requested`; otherwise, a missing size included, it raises `SizeAdjustedError`.
- **`DealingRules.validate(order: OrderRequest) -> None`:**
  - `min_deal_size`, `max_deal_size` and `min_size_increment` must be in `POINTS`, or it raises `ValidationError(f"cannot check size: {rule} is in {unit}")`;
  - it then raises when the size is under the minimum, over the maximum, or `size % increment != 0`.
- **`MarketDetails.validate(order: OrderRequest) -> None`** raises when `order.epic != instrument.epic`, then calls `dealing_rules.validate`. Its docstring says stop and profit distances are left to the server (ruling 3).
- The comment in `from_api` about `reason`/`rejectReason` records that demo sends `rejectReason`.

- [ ] **Step 1: Write the failing tests.** Use the confirmations in the Facts table:
  - an open gives `position_id == "P1"` with `deal_id == "D1"`;
  - netting (`[FULLY_CLOSED]`) and a rejection (`[]`) give `None`;
  - `require_size(Decimal("0.00015"))` on size `0.00010` raises `SizeAdjustedError` whose `confirmation.position_id == "P1"`; `Decimal("0.0001")` returns the confirmation;
  - a `rejectReason`-only payload gives `reason == "RC_NOT_ENOUGH_MARGIN"`;
  - for BTCUSD rules (min 0.0001, max 50, increment 0.0001), sizes `0.00005`, `51` and `0.00015` raise, and `0.0002` passes;
  - a `PERCENTAGE` min size raises `"cannot check size"`;
  - an order for `EURUSD` against SILVER details raises.
- [ ] **Step 2: Run** `pytest tests/unit/domain/test_confirmation.py tests/unit/domain/test_market_details.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(domain): add position id, booked-size check and size validation`.

### Task 4: Position and working-order read models

**Files:**
- Create `src/capitalcom/domain/positions.py` and `src/capitalcom/domain/working_orders.py`.
- Create the fixtures in `tests/unit/trading_payloads.py`: `position_item(deal_id="P1", **position)` and `order_item(deal_id="W1", **data)`, trimmed from the OpenAPI samples. Market rows come from `market_payloads.market_row`; `marketData` drops `pipPosition` and `tickSize`.
- Tests: `tests/unit/domain/test_positions.py`.

**Interfaces (Produces):**
- **`Position`:**
  - Fields: `deal_id`, `deal_reference`, `currency` (str); `direction: Direction`; `size`, `level`, `leverage`, `upl`, `contract_size` (Decimal); `created: datetime` (from `createdDateUTC`); `guaranteed_stop: bool`; `trailing_stop: bool`; `stop_level`, `profit_level: Decimal | None`; `working_order_id: str | None`; `market: Market`; `raw`.
  - `trailing_stop` is `False` when the key is absent, because the server omits it whenever no stop is set; the docstring says so.
  - `Position.from_api(item)` reads `position` and `market`; `positions_from(body) -> tuple[Position, ...]` reads `positions`.
- **`WorkingOrder`:**
  - Fields: `deal_id`, `epic`, `order_type`, `time_in_force`, `currency` (from `currencyCode`), `instrument_name` (from `marketData`) (str); `direction: Direction`; `size` (from `orderSize`), `level` (from `orderLevel`), `leverage` (Decimal); `good_till: datetime | None` (from `goodTillDateUTC`); `created: datetime`; `guaranteed_stop`, `trailing_stop` (bool); `stop_distance`, `profit_distance`, `stop_level`, `profit_level` (`Decimal | None`, distances signed as listed); `raw`.
  - `working_orders_from(body)` reads `workingOrders`.

- [ ] **Step 1: Write the failing tests:**
  - `position_item()` parses with `market.pip.size == Decimal("0.01")`, `stop_level is None` and `trailing_stop is False`.
  - With `stopLevel=67047.44, trailingStop=False` it gives `stop_level == Decimal("67047.44")`.
  - `order_item(stopDistance=-3724.38)` gives `stop_distance == Decimal("-3724.38")`, `good_till` in UTC, and `order_type == "LIMIT"`.
  - A GOOD_TILL_CANCELLED item without `goodTillDateUTC` gives `good_till is None`.
  - A missing `dealId` raises `ResponseFormatError`.
- [ ] **Step 2: Run** `pytest tests/unit/domain/test_positions.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(domain): add position and working-order read models`.

### Task 5: `cc.positions`

**Files:**
- Create `src/capitalcom/api/dealing.py` and `src/capitalcom/api/positions.py`.
- Modify `api/client.py`.
- Test: `tests/unit/api/test_positions.py`.

**Interfaces:**
- **Consumes:** Tasks 2–4.
- **Produces `submit(core: Core, method: str, path: str, body: Mapping[str, Any] | None = None) -> DealConfirmation`:**
  - sends the request;
  - reads `dealReference` with `require_str`;
  - returns `core.confirmer.confirm(ref).unwrap()`.
- **Produces `PositionsResource(core)`:**
  - `list() -> tuple[Position, ...]`;
  - `get(position_id: str) -> Position`;
  - `open(epic, direction, size, *, stop=None, profit=None, instrument: MarketDetails | None = None) -> DealConfirmation` builds an `OrderRequest`, calls `instrument.validate(request)` when an instrument is given, submits `POST /positions`, then returns `.require_size(request.size)`;
  - `amend(position_id: str, *, stop: StopLoss | None, profit: TakeProfit | None) -> DealConfirmation` sends `PUT` with `protection_body`. Its docstring states: "replaces all protection; `None` removes it";
  - `close(position_id: str) -> DealConfirmation` sends `DELETE /positions/{id}`.
- **Client:** `CapitalCom.positions`.

- [ ] **Step 1: Write the failing tests** (`responses`, confirmation mocked at `/confirms/o_1`):
  - `open("BTCUSD", Direction.BUY, Decimal("0.0001"), stop=StopLoss(distance=5))` sends the JSON `{"epic": "BTCUSD", "direction": "BUY", "size": 0.0001, "stopDistance": 5}` and returns `position_id == "P1"`.
  - A rejected confirmation raises `DealRejectedError`. A booked size of 0.00010 for a request of 0.00015 raises `SizeAdjustedError`.
  - `open(..., instrument=MarketDetails.from_api(details("BTCUSD") with `minDealSize` and `minSizeIncrement` set to 0.0001))` with size `0.00015` raises `ValidationError` and sends nothing.
  - `amend("P1", stop=None, profit=TakeProfit(level=9))` sends exactly `{"profitLevel": 9}`. `amend("P1", profit=None)` raises `TypeError`.
  - `close("P1")` sends `DELETE .../positions/P1`. `close("")`, `close("..")` and `get("..")` raise `ValidationError` with no request sent.
  - `list()` and `get("P1")` parse `position_item()`.
- [ ] **Step 2: Run** `pytest tests/unit/api/test_positions.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** and wire `self.positions` into `CapitalCom`.
- [ ] **Step 4: Run** `pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): add positions namespace`.

### Task 6: `cc.orders`

**Files:**
- Create `src/capitalcom/api/orders.py`.
- Modify `api/client.py`.
- Test: `tests/unit/api/test_orders.py`.

**Interfaces (Produces):** `OrdersResource(core)`:
- `list() -> tuple[WorkingOrder, ...]`.
- `create(epic, direction, size, *, level, type: OrderType | str, good_till: datetime | None = None, stop=None, profit=None, instrument=None) -> DealConfirmation` validates `request.order`, submits `POST /workingorders`, then calls `.require_size`.
- `amend(order_id: str, *, good_till: datetime | None, stop: StopLoss | None, profit: TakeProfit | None, level: Decimal | int | None = None) -> DealConfirmation` sends `PUT` with `level` (when given), `goodTillDate` (when given) and `protection_body`. Its docstring says the server drops anything left out.
- `cancel(order_id: str) -> DealConfirmation` sends `DELETE /workingorders/{id}`.
- Client: `CapitalCom.orders`.

- [ ] **Step 1: Write the failing tests:**
  - `create("BTCUSD", "BUY", Decimal("0.0001"), level=30000, type="LIMIT", good_till=<aware +02:00>)` sends `goodTillDate` in UTC and returns a confirmation whose `deal_id == "W1"`.
  - `amend("W1", good_till=None, stop=None, profit=None, level=25000)` sends exactly `{"level": 25000}`. `amend("W1", stop=None, profit=None)` raises `TypeError`. A naive `good_till` raises before sending.
  - `cancel("..")` raises with no request sent. `cancel("W1")` sends `DELETE .../workingorders/W1`.
  - `list()` parses `order_item()`.
- [ ] **Step 2: Run** `pytest tests/unit/api/test_orders.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** and wire `self.orders`.
- [ ] **Step 4: Run** `pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): add working orders namespace`.

### Task 7: Exports, contract tests, ADRs, gates

**Files:**
- Modify `src/capitalcom/__init__.py`, `test_public_exports`, `tests/contract/conftest.py`, `docs/adr/0007-*.md`, and spec §6.1/§6.2 to match rulings 2, 3 and 5 (the spec stays ≤300 lines).
- Create `tests/contract/test_trading_contract.py` and `docs/adr/0010-trading.md`.

- [ ] **Step 1: Exports, RED then GREEN.** Export `StopLoss`, `TakeProfit`, `OrderRequest`, `WorkingOrderRequest`, `OrderType`, `Position`, `WorkingOrder` and `SizeAdjustedError`, after checking them for collisions with the legacy star-import.
- [ ] **Step 2: Contract tests.** Use the resources over `demo_core`, with the `btc` fixture plus a new `btc_orders` sweep fixture in `conftest.py` that deletes orders not in the snapshot taken before the test.
  - **`test_position_round_trip`:**
    - `open` at min size with `StopLoss(distance=5% of bid)` and `TakeProfit(distance=5% of bid)`;
    - `get(position_id)` has both levels, and `profit_level == level + distance` (pins the inferred reference);
    - `amend(stop=StopLoss(level=90% of bid), profit=None)` leaves `profit_level is None`;
    - `close`, after which `get` raises `NotFoundError`.
  - **`test_position_size_rules`:** validated off-grid size raises `ValidationError`; unvalidated size 1.5×min raises `SizeAdjustedError`, whose position is then closed; `maxDealSize` raises `DealRejectedError` with a non-empty `reason`.
  - **`test_netting_open`:** open BUY at min size, then SELL at min size: no `SizeAdjustedError`, and the SELL's `position_id is None`; log the SELL's `status` and affected statuses.
  - **`test_order_round_trip`:** `create` LIMIT BUY at 50% of the bid with `good_till` +1 day; it is listed under `deal_id` with that `good_till`; `amend(level=45%, same good_till, stop=None, profit=None)` keeps `good_till`; `cancel` removes it from the list.
- [ ] **Step 3: ADRs.**
  - ADR 0010 records the Facts and Rulings 1–7, with an Observations table filled in after CI.
  - ADR 0007: the rejection row becomes observed (`rejectReason`, status `DELETED`, no affected deals).
- [ ] **Step 4: Gates.**
  - `ruff check .`, `ruff format --check .` and `mypy`;
  - `pytest -q`, coverage ≥95;
  - the 300-line check;
  - local Semgrep with the 2b command.

  Expected: all green.
- [ ] **Step 5: Commit** `feat: export stage 2c models, add trading contract tests and ADR 0010`.
- [ ] **Step 6: Final review.** Run `/code-review high` over the 2c commits, then do one RED→GREEN fix pass.
- [ ] **Step 7: Push** to `rewrite/stage-2-rest`. Read the contract log, fill in the ADR 0010 Observations table, and commit `docs(adr): record stage 2c contract observations`. Then take PR #4 out of draft once CI is green; the owner decides on the merge. Update the stage status in the owner's notes.
