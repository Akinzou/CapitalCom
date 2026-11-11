# Migrating from `CapitalClient` (1.x) to `CapitalCom` (2.x)

`CapitalClient` still works in 2.x, with the same signatures and return values. It is
deprecated and will be removed in 3.0. Each of its names emits one `DeprecationWarning`.
Python hides these by default; run with `-W default::DeprecationWarning` to see them.

## The client

```python
# 1.x
from capitalcom import CapitalClient

client = CapitalClient(api_key, login, password, demo=True)

# 2.x
from capitalcom import CapitalCom, Environment

with CapitalCom(api_key, login, password, environment=Environment.DEMO) as cc:
    ...
```

Differences:
- `CapitalCom` logs in on the first call, not in the constructor.
- `with` or `cc.close()` logs out; 1.x never did.
- Numbers are `Decimal`, and results are typed objects instead of raw dicts.
- Convert a float with `Decimal(str(x))`, never `Decimal(x)`: `Decimal(0.1)` is
  `0.1000000000000000055…`, and 2.x refuses a number it would have to round.

## Call by call

| 1.x | 2.x |
|---|---|
| `open_raw_position(epic, size, direction, stop_dist, profit_dist)` returns the dealId | `deal = cc.positions.open(epic, direction, Decimal(str(size)), stop=StopLoss(distance=...), profit=TakeProfit(distance=...))`, then `deal.position_id` |
| `open_forex_position(epic, lots, direction, stop_pips, profit_pips)` | `cc.positions.open(...)` with `size` in units and distances in price units. 1.x scaled distances by 0.00001, which is wrong for JPY pairs |
| `close_position_by_id(deal_id)` returns `"SUCCESS"` | `cc.positions.close(position_id)` returns the confirmation; a rejection raises `DealRejectedError` |
| `close_position_by_id(deal_id, size=...)` | Not available: Capital.com closes the whole position whatever size is sent, so `positions.close` takes no size, and the 1.x call now raises `ValidationError` |
| `close_position_by_ref(deal_reference)` | `cc.positions.close(deal.position_id)`, keeping the confirmation of the open |
| `get_deal_by_ref(deal_reference)` | Not needed: `positions.open` waits for the confirmation and returns it |
| `get_open_positions()` returns raw dicts | `cc.positions.list()` returns `Position` objects |
| `get_balance(account_id, raw)` | `cc.accounts.list()`; the 1.x number is `account.balance.balance` |
| `list_accounts()` | `cc.accounts.list()`; 2.x does not log balances |
| `top_up_demo(amount)` | `cc.accounts.top_up(Decimal(str(amount)))` |
| `test_trade()` | No equivalent |
| `lot_to_size(lot, lot_size)`, `pips_to_profit_distance(pips, pip_position)` | Plain arithmetic in your code |
| `login_session()` | Not needed: the session renews itself |
| `_request(method, path, ...)` | Not public. Tell us which endpoint you need |
| `cst`, `security_token`, `token_expiry` | Managed inside the client |
| `colored_log(level, text)` | `logging.getLogger("capitalcom")`; configure handlers in your application |

## Errors

1.x raised bare `Exception` for server errors and `requests` exceptions for network failures.
2.x raises subclasses of `CapitalComError`, which derives from `Exception`, so
`except Exception` keeps working. The legacy `CapitalClient` raises network failures as
`LegacyTransportError`, which is both a `TransportError` and a
`requests.exceptions.ConnectionError`, so 1.x retry clauses still catch them; `CapitalCom`
raises a plain `TransportError`. To handle a case precisely, catch the specific class:
- `AuthenticationError`;
- `DealRejectedError` (its `reason` says why);
- `OutcomeUnknownError`: a trade request timed out and was not resent, so check your
  positions before trying again;
- `ValidationError`;
- `ApiError`.

## Logging

1.x configured the root logger at import and coloured its messages. 2.x does neither. To see
the library's logs:

```python
import logging

logging.basicConfig(level=logging.INFO)
```
