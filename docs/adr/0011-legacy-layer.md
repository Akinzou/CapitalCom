# 11. The 1.x `CapitalClient` on top of the 2.x core

- Status: accepted
- Date: 2026-11-12

## Context

`capitalcom.client.CapitalClient` is the whole 1.0.4 API, and existing bots call it. Spec §7
keeps every 1.0.4 name working, with the same signature and return shape, until 3.0. Only a
short list of deliberate behaviour changes is allowed. The layer must not be a second
client: one transport, one session manager, one rate limiter.

## Decisions

### The 1.0.4 behaviour is pinned by characterization, not by reading

The golden suite (`tests/legacy/golden/`) was written first and run against the untouched
1.0.4 module. Every test passed there before any line of the module changed. It then stayed
green through the rewrite. Behaviour that changes on purpose has its own tests
(`tests/legacy/test_changes_*.py`), each of which failed against 1.0.4.

### Shape

- `client.py` keeps the class, the four colour constants and `colored_log`. The helpers live
  in `capitalcom.legacy` (`wiring`, `raw_request`, `trading`, `accounts`, `attributes`,
  `deprecation`), which is not public API.
- The client owns a `requests.Session` and builds a `Core` around it, so proxies, adapters
  and headers set on `client.session` apply to every call.

### `_request` stays a raw escape hatch

1.0.4 callers read `status_code` themselves, so `_request` returns a `requests.Response`
for any status. It cannot go through the dispatcher, which turns statuses into errors.
Instead it:
- takes tokens from the session manager and waits on the core's rate limiter;
- always sends `verify=True` and `allow_redirects=False`, and refuses a caller's `verify` or
  `allow_redirects` with `ValidationError`, because a redirect would carry the session tokens
  to another host;
- uses a `(5, 15)` s timeout unless the caller gives one (1.0.4 had none);
- keeps 1.0.4's loop: one re-login on the first 401, a 1 s wait on a 429, ten attempts.

### Opens send the 1.0.4 body

`open_raw_position` posts exactly what 1.0.4 posted, floats included, through the core's
`submit`, then waits for the confirmation. It does not go through `positions.open`:
- `OrderRequest` refuses floats such as `0.001 * 100000`;
- dropping `forceOpen`, `orderType` or `expiry` would change a request whose effect was never
  observed.

### Ids, netting and rounded sizes

- The returned id is `affectedDeals[0].dealId`, whatever its status, as in 1.0.4. That is the
  position for an open (ADR 0007).
- An accepted deal with no affected deals (an opposite open netting against a position, ADR
  0010) raises `CapitalComError` saying no position was opened. 1.0.4 raised there too, after
  its retries ran out. A guessed id would be closed by mistake later.
- A size the server rounded is logged as a WARNING and the id is returned. `SizeAdjustedError`
  would break 1.0.4 code for a deal that is booked.
- `get_deal_by_ref(retries, delay)` polls at most `retries` times, `delay` seconds apart, then
  raises `ConfirmationTimeoutError`.

### Closing

- `close_position_by_id` uses the documented `DELETE /positions/{dealId}` and waits for the
  confirmation; a rejection raises.
- A truthy `size` raises `ValidationError` before anything is sent: the legacy endpoint closes
  the whole position whatever size is sent (ADR 0007). `size=0` stays a full close, as 1.0.4
  tested `size` for truthiness.
- `test_trade` closes by id. 1.0.4 passed the dealId to `close_position_by_ref`, which asked
  `/confirms` with it; if that never resolved, the test position stayed open.

### Attributes

- `api_key`, `login`, `password`, `session` and `base_url` are read-only. The core was built
  from them, so assigning a new value would be ignored without a word; `AttributeError` says
  so instead. `repr()` shows only the host.
- `cst` and `security_token` read the session manager, and their setters push a new token
  pair into it; `None` drops the session.
- `token_expiry` is the wall-clock time when the idle session expires, or `0` without one.
  Setting a past time drops the session, as it forced a login in 1.0.4. A future time cannot
  keep a session alive on the server, and the core renews on its own timer.

### Warnings, logging and exports

- `DeprecationWarning` fires once per name and process, on the constructor and every public
  method, with a link to `docs/migration.md`. `_headers` and `_request` are private and do
  not warn. `open_forex_position`'s warning names its JPY flaw: it scales distances by
  0.00001, so JPY pairs, quoted to three decimals, get distances 100 times too small.
- `colored_log` logs under `capitalcom.client` without colours, and the module no longer calls
  `logging.basicConfig`.
- `client.__all__` lists the six 1.x names. 1.0.4's star import also leaked the `requests`,
  `time`, `logging` and `random` modules; they are no longer re-exported.

### Errors

- HTTP errors are the typed 2.x errors, all subclasses of `Exception`.
- Network failures are raised as `LegacyTransportError`, a `TransportError` that is also a
  `requests.exceptions.ConnectionError`. In 1.0.4 they were `requests` exceptions, and bots
  retry on those; a plain `TransportError` would stop such a bot on the first network blip.
  `OutcomeUnknownError` stays outside that hierarchy, so a retry clause cannot resend a trade.
- Errors 1.0.4 raised without an HTTP status become `CapitalComError`, for example "No
  accounts found.". A body that is not a JSON object raises `ResponseFormatError`.
- `top_up_demo` raises `ApiError` when the server answers `"successful": false`; 1.0.4
  returned `None` for that.

### Kept as 1.0.4 did it

- `get_balance(raw=True)` reads `available` beside `balance`, where 1.0.4 looked. The server
  sends it inside `balance`, so the value is `None`, as it always was.
- The forex maths: `lot * 100000`, `pips * 1e-5`.
- Float amounts and sizes, with no local checks: the legacy path makes no extra request and
  raises nothing 1.0.4 did not.

## Consequences

- Public methods still call each other through `self` (`open_forex_position` through
  `lot_to_size`, `pips_to_profit_distance` and `open_raw_position`; `close_position_by_ref`
  through `get_deal_by_ref` and `close_position_by_id`; `test_trade` through both), so a
  subclass guard or a JPY fix in an override keeps applying. Overriding `_request` or
  `login_session` no longer changes how they reach the server.
- A bug in the 2.x core now reaches 1.x users too. The golden suite and the legacy contract
  test (`test_legacy_round_trip`) run in CI to catch it.
- The layer is deleted in 3.0, with `capitalcom.legacy` and the golden suite.
