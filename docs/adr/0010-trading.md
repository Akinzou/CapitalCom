# 10. Trading: positions and working orders

- Status: accepted
- Date: 2026-11-11

## Context

Stage 2c adds `cc.positions` and `cc.orders`. The documentation lists the request fields, but
not what the server does with a field that is left out, nor how it checks limits. One demo probe
run on 2026-11-11 (BTCUSD, BUY, a CFD account with hedging off) observed the following:

- **An amend replaces; it does not merge.**
  - `PUT /positions/{id}` with only `profitLevel` removed the existing stop.
  - With only `stopDistance`, it removed the take-profit, and `{}` removed both.
  - `PUT /workingorders/{id}` with only `level` dropped `goodTillDate` (the order became
    `GOOD_TILL_CANCELLED`) and its stop distance. Leaving `level` out kept the level.
- **Confirmations** (`status`, then the statuses of the affected deals):

  | Action | Confirmation |
  |---|---|
  | Open a position | `OPEN`, `[OPENED]`. The affected deal is the position; the top-level `dealId` is not (ADR 0007) |
  | Amend a position | `AMENDED`, `[AMENDED]` |
  | Close a position | `CLOSED`, `[FULLY_CLOSED]` |
  | Create an order | `OPEN`, `[OPENED]`. The affected deal and `dealId` are both the order id |
  | Amend an order | `AMENDED`; the id is kept |
  | Cancel an order | `DELETED`, `[DELETED]` |
  | Rejection | `dealStatus` `REJECTED`, `status` `DELETED`, no affected deals, the reason under `rejectReason` |

- **The server rounds the size down without saying so.** An open of 0.00015, where the
  increment is 0.0001, was accepted and booked as 0.00010.
- **Size rules on all 4011 demo markets:**
  - Size rules are in `POINTS`. Every minimum lies on its increment grid.
  - Stop and profit distance rules are in `PERCENTAGE`.
  - `trailingStopsPreference` is `NOT_AVAILABLE` on every market.
- **The server checks distance limits on the resulting level, against the live quote.**
  - A take-profit 150% away was accepted, although `maxStopOrProfitDistance` is 100%.
  - A stop just under the bid answered 400 `error.invalid.stoploss.maxvalue: 74490.85`. The
    error code carries the limit price.
  - A distance counts from the position's open level. This was inferred, and the contract
    test pins it.
- **Other refusals:**
  - stop level together with stop distance: `error.conflict.stoploss.types`;
  - guaranteed stop with no stop: `error.null.stoploss.value`;
  - trailing stop with no distance: `error.null.stopDistance.value`;
  - a STOP order on the wrong side of the price: `error.validation.stop.price`;
  - a past `goodTillDate`: `error.not-in-future.goodTillDate`;
  - a malformed deal id: 400 `error.invalid.dealId`.
- **Rows:**
  - A position's `market` row carries `pipPosition` and `tickSize`; an order's `marketData`
    does not.
  - `stopLevel`, `profitLevel` and `trailingStop` are absent when unset.
  - A stop set by distance or amount is listed as `stopLevel`.
  - An order's stop distance is listed signed: sent as 3724.38, listed as -3724.38.

## Decisions

### Amend takes the whole protection state

`positions.amend(position_id, *, stop, profit)` and
`orders.amend(order_id, *, good_till, stop, profit, level=None)` have required keyword
arguments. Leaving one out is a `TypeError`, and `None` removes that part.

With a merge-style `amend(profit=...)`, a caller changing the take-profit would silently lose
the stop, and a position without a stop is the failure that costs money. Reading the current
state and merging into it was rejected:
- It costs a hidden request.
- It depends on row shapes the probe did not cover: trailing and guaranteed stops, SELL, and
  re-sent order distances, which are signed.

Required arguments can later become optional-and-kept without breaking a caller. The reverse
would break callers.

### Stops are values that cannot be built wrong

`StopLoss` takes exactly one of `level`, `distance` or `amount`, plus `guaranteed` and
`trailing`. It refuses:
- two kinds at once;
- guaranteed and trailing together;
- a trailing stop without a distance.

`TakeProfit` takes exactly one of the three. Caller numbers must be `Decimal` or `int`,
finite and greater than zero. Spec §6.1 is updated: `amend(deal.position_id, stop=...,
profit=...)`.

### Pre-trade validation checks sizes only

`MarketDetails.validate(order)` checks:
- the epic;
- the minimum and maximum size;
- the size increment, measured from zero.

A size rule in any unit other than `POINTS` raises `ValidationError` instead of being
skipped. Stop and profit distances are not checked: the server judges the resulting level
against a quote that moves, so a local check would have refused the accepted 150%
take-profit. Spec §6.2 is updated.

### A rounded size raises

After every open or order create, a booked size different from the requested one raises
`SizeAdjustedError(requested, confirmation)`. The deal already exists, so the error carries
the confirmation and its `position_id`, and the caller can close the deal or keep it.

### Ids

`DealConfirmation.position_id` is the first affected deal with status `OPENED`. It is `None`
when nothing opened, as when an opposite deal nets against a position. For a created order it
is the order id, as is `deal_id`.

### Deferred and left verbatim

- **The "real stocks" rule.** It is deferred: the demo has only a CFD account, so how the
  server reports the rule cannot be observed, and the server stays authoritative.
- **Error codes.** `ApiError.error_code` keeps suffixes such as `: 74490.85`; splitting them
  would guess a format the documentation does not give.

## Observations (demo, contract tests of stage 2c)

To be filled in from the first CI run of these tests on PR #4.

| Question | Observed | Pinned by |
|---|---|---|
| Open with distances, read levels, amend, close | | `test_position_round_trip` |
| Does a profit distance count from the open level? | | `test_position_round_trip` |
| Off-grid size: refused by `validate`, rounded by the server | | `test_position_size_rules` |
| Rejection reason of an oversized open | | `test_position_size_rules` |
| Netting: SELL against an open BUY | | `test_netting_open` |
| Create, amend (keeping `good_till`) and cancel an order | | `test_order_round_trip` |

## Consequences

- Changing only the take-profit means passing the current stop again. The docstrings say
  this.
- An off-grid size is caught before sending only when the caller passes `instrument=`.
  Without it, the server rounds the size and the client raises after the deal is booked.
- If Capital.com starts merging amends or stops rounding sizes, the contract tests show it;
  revisit this ADR then.
