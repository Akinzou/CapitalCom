# Trading

`cc.positions` opens, amends and closes positions at market. `cc.orders` places, amends and
cancels working orders at a level. Every call that changes something waits for the server's
confirmation before it returns. Read [Errors and reliability](reliability.md) before trading
on a live account.

## Sizes, levels and distances are `Decimal`

Sizes, levels, distances and amounts are `Decimal` or `int`. A `float` raises
`ValidationError`, because it may already carry a binary rounding error.

Convert a float with `Decimal(str(x))`, never `Decimal(x)`. `Decimal(0.1)` is
`0.1000000000000000055…`, and the client refuses any `Decimal` with more than 15 significant
digits instead of letting the server round it to a size or level you did not ask for
([ADR 0005](../adr/0005-error-model.md)).

Prices, sizes and money the server returns are `Decimal` as well.

## Opening a position

```python
--8<-- "docs/examples/trading.py:open"
```

`cc.positions.open(epic, direction, size, stop=..., profit=..., instrument=...)` sends the
order, waits for its confirmation and returns it as a `DealConfirmation`.

- `direction` is `Direction.BUY` or `Direction.SELL`.
- `instrument=` takes the `MarketDetails` from `cc.markets.get(epic)` and checks the size
  against its dealing rules before sending: the epic, the minimum and maximum size, and the
  size increment. Stop and profit distances are not checked locally; see below.
- `stop` and `profit` are optional; see [Stop-loss and take-profit](#stop-loss-and-take-profit).

## Confirmations

A trade request only returns a deal reference. The client then polls the confirmation every
0.1 s, starting no new poll once `confirm_timeout` seconds (5 by default, set on
`CapitalCom`) have passed, and returns once the server has accepted or rejected the deal:

- accepted: the `DealConfirmation` is returned, with `deal_status`, `status`, `epic`,
  `direction`, `level`, `size`, `affected_deals` and the UTC `date`;
- rejected: `DealRejectedError` is raised, and its `reason` holds the server's reason;
- neither in time: `ConfirmationTimeoutError` is raised, and the deal may still execute.

Which id to keep ([ADR 0007](../adr/0007-partial-close-and-confirmation-facts.md),
[ADR 0010](../adr/0010-trading.md)):

- For a new position, keep `confirmation.position_id`. It is the id that `positions.get`,
  `amend` and `close` take, and the `deal_id` of the position in `cc.positions.list()`.
  The confirmation's own `deal_id` is not the position.
- For a working order, keep `confirmation.deal_id`, which is the order id.

## The server may round the size

The server rounds a size that is off its increment grid down, without saying so: an open of
0.00015 where the increment is 0.0001 was booked as 0.00010. After every open and order
create, a booked size other than the one requested raises `SizeAdjustedError`
([ADR 0010](../adr/0010-trading.md)).

The deal exists when this is raised. `error.confirmation` is its confirmation, with the
booked `size` and the `position_id`, and `error.requested` is the size you asked for. Close
the deal or keep it; the example above keeps it. Passing `instrument=` refuses an off-grid
size before anything is sent.

## Stop-loss and take-profit

`StopLoss` takes exactly one of `level` (a price), `distance` (from the price) or `amount`
(money), plus the flags `guaranteed` and `trailing`. These are refused when the value is
built, with `ValidationError`:

- two of `level`, `distance` and `amount` at once, or none;
- a stop both guaranteed and trailing;
- a trailing stop without a distance;
- a number that is not greater than zero.

`TakeProfit` takes exactly one of `level`, `distance` or `amount`
([ADR 0010](../adr/0010-trading.md)).

The server, not the client, judges the distance limits. It checks the resulting level against
the live quote, so a local check against the percentage rules would refuse orders the server
accepts. A distance counts from the position's open level. A level the server refuses comes
back as an `ApiError` whose `error_code` carries the limit, such as
`error.invalid.stoploss.maxvalue: 74490.85` ([ADR 0010](../adr/0010-trading.md)).

On the demo server `trailingStopsPreference` was `NOT_AVAILABLE` on every market
([ADR 0010](../adr/0010-trading.md)).

## Amending a position

```python
--8<-- "docs/examples/trading.py:amend"
```

An amendment replaces all protection; it does not merge. `cc.positions.amend(position_id,
stop=..., profit=...)` therefore requires both keyword arguments:

- to keep a stop or take-profit, pass it again;
- to remove one, pass `None`;
- leaving an argument out raises `TypeError`.

A merge-style amend would silently drop the stop of a caller who only changed the
take-profit, and a position without a stop is the failure that costs money
([ADR 0010](../adr/0010-trading.md)).

## Closing a position

```python
--8<-- "docs/examples/trading.py:close"
```

`cc.positions.close(position_id)` closes the whole position. There is no partial close:
Capital.com ignores a size sent with the close and closes everything, so the call takes no
size ([ADR 0007](../adr/0007-partial-close-and-confirmation-facts.md)).

`cc.positions.list()` returns every open `Position`, and `cc.positions.get(position_id)`
one of them; a closed position raises `NotFoundError`.

## Working orders

```python
--8<-- "docs/examples/trading.py:order"
```

`cc.orders.create(epic, direction, size, level=..., type=..., good_till=..., stop=...,
profit=..., instrument=...)` places an `OrderType.LIMIT` or `OrderType.STOP` order at
`level`. Without `good_till` the order runs until cancelled; with it, `good_till` must be a
timezone-aware `datetime`. A created order can also raise `SizeAdjustedError`.

`cc.orders.amend(order_id, good_till=..., stop=..., profit=..., level=...)` replaces the
expiry and all protection, like a position amend:

- `good_till`, `stop` and `profit` are required keywords;
- `good_till=None` makes the order good until cancelled;
- only `level` may be left out, and it is then kept.

`cc.orders.cancel(order_id)` deletes the order, and `cc.orders.list()` returns every
`WorkingOrder` ([ADR 0010](../adr/0010-trading.md)).

## Netting

An opposite deal can net against an open position instead of opening a new one. On the
demo account the probes used (hedging off), a SELL of the same size as an open BUY returned
status `OPEN` with no affected deals, `position_id` was `None`, and the BUY was gone
([ADR 0010](../adr/0010-trading.md)).

So check `position_id` for `None` before using it, as the examples do. Only equal sizes were
observed netting: a netting open of another size may report a size that differs from the
request and raise `SizeAdjustedError` for a deal that was booked as asked. The error carries
the confirmation, so nothing is lost.
