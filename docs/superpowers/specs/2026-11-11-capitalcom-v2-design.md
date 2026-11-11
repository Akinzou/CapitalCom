# capitalcom 2.0 — Design

Status: approved by owner 2026-11-11 · Date: 2026-11-11 · Branch: `rewrite/v2-design`

## 1. Intent

`capitalcom` is a Python client for the Capital.com REST API (demo and live). Version 1.0.4 is a
single 286-line file that covers about a quarter of the public API. Version 2.0 rewrites it to
professional quality: full coverage of the documented REST API, typed models, typed errors, real
rate-limit and session handling, tests, CI gates, and MkDocs documentation. Existing user code
must keep working.

### What we know about users (recon, 2026-11-11)
- About 39 downloads a month. The "10k+" figure is cumulative and mostly mirrors and bots.
- About 95% of downloads with a known version are on Python 3.11 or newer. No downloads on 3.8.
- The only confirmed public consumer calls `CapitalClient(...)` and
  `open_raw_position(direction=..., epic=..., size=...)`. It then tries eight guessed method
  names to close a position, which shows the current API cannot be discovered.
- Another, unrelated library also installs a top-level `capitalcom` module
  (`capitalcom.client_demo`, `Client`). Installing ours breaks code written for it.

## 2. Goals

1. Full coverage of the public REST API documented at https://open-api.capital.com/:
   - Session: plain and RSA-encrypted login, keepalive, account switch, logout.
   - Accounts: preferences, activity and transaction history, demo top-up.
   - Trading: positions (open, read, amend, close) and working orders (LIMIT and STOP).
   - Confirmations.
   - Markets: navigation, search, details, historical prices, client sentiment.
   - Watchlists.
2. Backward compatibility. Every public 1.0.4 name keeps working with the same signature and the
   same return shape (section 7).
3. A migration guide that maps each legacy call to its 2.0 equivalent.
4. Correct trading semantics:
   - A trade operation succeeds only after `/confirms` reports it accepted.
   - A broker rejection raises a typed error.
   - Non-idempotent requests are never blindly retried.
5. A discoverable, fully typed API. IDEs and LLM-based tools can find "close a position" without
   guessing.
6. WebSocket streaming (quotes and OHLC), as a separate stage after the REST core (section 9).
7. MkDocs documentation site, as the last stage.

## 3. Non-goals (2.0)
- An async API. Ports keep it addable later without rewriting logic.
- A CLI, backtesting, strategy framework, pandas integration, or MCP server. Capital.com
  publishes its own MCP server.
- Renaming the `capitalcom` import package. The collision is documented, not fixed.

## 4. Anti-goals: failure even if it "works"
- Existing user code breaks on upgrade.
- The library configures the host application's logging or prints ANSI colours into its logs.
- An order rejected by the broker is reported as success.
- A network retry opens a second position.
- Credentials or session tokens appear in logs, `repr()`, exception messages, or test fixtures.

## 5. Constraints
- Python `>=3.11`. Runtime dependency: `requests` only. RSA login is an optional extra,
  `capitalcom[encryption]`, which pulls in `cryptography`.
- Package layout: `src/capitalcom/`. Every hand-written file stays at or under 300 lines.
- Clean Architecture with Ports & Adapters. A port exists only where the code crosses a process
  boundary: HTTP, WebSocket, and the clock (time and sleep). Pure logic lives in domain
  functions and entity methods.
- Errors: typed exceptions on the public surface. Internally, ports and application services
  return `Result`. The public facade is the single place where a `Result` becomes an exception.
- Version 2.0.0 follows SemVer. The legacy layer is deprecated and can be removed no earlier
  than 3.0.
- License: see section 11.

## 6. Architecture

```
src/capitalcom/
  __init__.py        public exports: CapitalCom, CapitalClient (legacy), errors, models, enums
  domain/            values, entities, pure rules (no I/O, no requests import)
  application/       ports, Result, session manager, rate limiter, deal confirmer, services
  infrastructure/    adapters: requests transport, system clock, (later) websocket
  api/               public facade: CapitalCom and its resource namespaces
  client.py          legacy CapitalClient; keeps `capitalcom.client.CapitalClient` importable
```

Dependencies point inward only: `api -> application -> domain` and
`infrastructure -> application`. `api` is also the composition root, so `api -> infrastructure`
is allowed (ADR 0003). A test fails the build on any import cycle or outward import.

### 6.1 Public API shape (new)

```python
from capitalcom import CapitalCom, Environment, Direction

with CapitalCom(api_key, identifier, password, environment=Environment.DEMO) as cc:
    deal = cc.positions.open(
        "EURUSD", Direction.BUY, size=Decimal("1000"), stop_distance=Decimal("0.0010")
    )
    cc.positions.amend(deal.deal_id, profit_level=Decimal("1.1000"))
    cc.positions.close(deal.deal_id)
```

- Namespaces: `session`, `accounts`, `history`, `positions`, `orders`, `markets`, `prices`,
  `sentiment`, `watchlists`, and later `stream`.
- Login is lazy, on the first call. `__exit__` and `close()` log out with `DELETE /session`.
- Trading calls return a `DealConfirmation` with the deal id, status, level, and affected deals.
- Numbers that represent money, prices, sizes, or distances are `Decimal`. JSON is parsed with
  `parse_float=Decimal`. Timestamps are timezone-aware UTC `datetime`.
- Models are frozen, slotted dataclasses. Each one also keeps the original payload in `.raw`, so
  fields Capital.com adds later are still reachable.

### 6.2 Domain: behaviour, not bags of fields
- `Instrument`:
  - `pip_size` comes from the API's `pipPosition`, not a hard-coded 5. This fixes JPY pairs.
  - `pips_to_distance()` and `lots_to_size()` use the instrument's `lotSize`.
- `DealingRules.validate(order)`: checks minimum and maximum size, size increment, and stop and
  profit distance before sending.
- `OrderRequest`: enforces the documented constraints:
  - `guaranteedStop` needs a stop, and cannot be combined with `trailingStop`.
  - `trailingStop` needs `stopDistance`.
  - Real stocks cannot carry a stop loss or take profit.
- `DealConfirmation.is_accepted`. An impossible state raises inside the domain; nothing is
  silently defaulted.
- **Pre-trade validation is opt-in (designer's call).**
  - `positions.open(...)` and `orders.create(...)` accept an optional `instrument=` (from
    `cc.markets.get(epic)`). When it is given, the request is validated locally before sending.
  - Without it, the server's validation is authoritative. This avoids a hidden extra request per
    trade and the need for a market-details cache in the core.
  - The "real stocks" rule applies when the instrument's `type` is `SHARES` and the account is
    not a CFD account. The stage-2 contract tests confirm how Capital.com reports this.

### 6.3 Application services
- **Session manager:**
  - Tokens are valid for 10 minutes after last use. It tracks last use through the `Clock` port
    and re-authenticates before expiry.
  - On a 401 it re-authenticates once and retries.
  - Token refresh is thread-safe (lock), because trading bots often use threads.
- **Rate limiter:**
  - Token buckets: 10 requests per second overall, one trade request per 0.1 s, one session
    creation per second.
  - A 429 is retried with exponential backoff and jitter. `Retry-After` is honoured if present.
  - The number of attempts can be configured.
- **Retry policy:**
  - GET, and anything rejected with 401 or 429, is safe to retry, because the server did not
    act on it.
  - A transport error such as a timeout on a POST, PUT, or DELETE is never retried. It raises
    `OutcomeUnknownError` and tells the caller to check positions.
- **Deal confirmer:** polls `/confirms/{dealReference}` through the `Clock` port with a
  configurable timeout. A rejected deal raises `DealRejectedError(reason)`. A timeout raises
  `ConfirmationTimeoutError`.

### 6.4 Errors (public)
- `CapitalComError(Exception)` is the root. Under it: `AuthenticationError`, `RateLimitError`,
  `NotFoundError`, `ValidationError` (local rule violation), `ApiError` (status, errorCode,
  body), `TransportError`, `OutcomeUnknownError`, `DealRejectedError`, and
  `ConfirmationTimeoutError`.
- Everything subclasses `Exception`, so legacy `except Exception` keeps working.
- Error body format: the official docs do not describe it. We observed it live on 2026-11-11:
  `{"errorCode": "error.invalid.api.key"}` with HTTP 401. `ApiError.error_code` is read from
  `errorCode`. Unknown codes map to `ApiError` and are never swallowed.

### 6.5 Security baseline (OWASP ASVS, as it applies to a client library)
- Every HTTP call has a connect and read timeout. In 1.0.4 there were none, so a call could hang
  forever.
- TLS verification is always on. There is no option to disable it.
- Secrets live in a `SecretStr`-style wrapper. The client's `repr` masks them.
- The logging filter never emits the `CST`, `X-SECURITY-TOKEN`, or `X-CAP-API-KEY` headers, the
  password, or the request body of `/session`.
- The library logs only to `logging.getLogger("capitalcom")` with a `NullHandler`. It never calls
  `basicConfig`.

## 7. Legacy compatibility layer (`capitalcom.client`)

`CapitalClient` delegates to the new core. Each public method emits `DeprecationWarning` once,
with a link to the migration guide.

| 1.0.4 surface | Preserved contract |
|---|---|
| `CapitalClient(api_key, login, password, demo=True)` | Logs in eagerly in the constructor |
| `open_raw_position(epic, size, direction, stop_dist=None, profit_dist=None)` | Returns the dealId as `str`; a falsy `stop_dist`/`profit_dist` is ignored |
| `open_forex_position(...)` | Same arguments and maths: `lot * 100000`, `pips * 1e-5`. The JPY flaw is kept and the warning names it |
| `close_position_by_id(deal_id, size=None)` | Returns `"SUCCESS"` |
| `close_position_by_ref(deal_reference, size=None)` | Resolves, then closes; returns `"SUCCESS"` |
| `get_deal_by_ref(deal_reference, retries=10, delay=0.1)` | Returns the dealId |
| `get_open_positions()` | Returns a list of raw `dict`s with floats, not `Decimal` |
| `get_balance(account_id=None, raw=False)` | Same return shapes |
| `list_accounts()` | Returns a list of raw dicts and logs each account at INFO |
| `top_up_demo(amount)` | Returns `None` |
| `test_trade()` | Same behaviour; it swallows errors and logs them |
| `lot_to_size`, `pips_to_profit_distance` | Pure and unchanged |
| Attributes `session`, `cst`, `security_token`, `base_url`, `token_expiry` | Present and kept in sync |
| `login_session()`, `_headers()`, `_request()` | Present; `_request` returns `requests.Response` |
| Module names `colored_log`, `RESET`, `GREEN`, `RED`, `BLUE` | Importable; `colored_log` logs without changing global config |

Deliberate behaviour changes, each listed in the CHANGELOG:
1. No `logging.basicConfig` at import, and no ANSI colours.
2. A full close (`size=None`) uses the documented `DELETE /positions/{dealId}` and waits for
   confirmation. A rejection now raises instead of returning `"SUCCESS"`.
3. Errors are typed subclasses of `Exception` instead of bare `Exception`.
4. A REJECTED confirmation on open raises `DealRejectedError`. In 1.0.4 it returned the dealId as
   if the trade had succeeded.
5. A write request that times out raises `OutcomeUnknownError` and is not retried. In 1.0.4 such a
   call could hang forever.

Legacy behaviour that is kept on purpose (designer's call):
- **Partial close (`size` given).** The documented endpoint has no size parameter. The legacy
  layer keeps sending 1.0.4's `DELETE /api/v1/positions` with `{dealId, size}` and confirms the
  result.
  - A stage-1 contract test on demo proves whether that endpoint really closes only part of the
    position.
  - If it does not, the call raises `ValidationError`. It never silently closes the whole
    position.
  - The 2.0 API exposes `positions.close(deal_id)` (full close only) until a documented
    partial-close mechanism is verified.
- **No local pre-trade validation on the legacy path.** It would add a `GET /markets/{epic}`
  call that 1.0.4 never made.
- **Legacy state is shared with the core, not copied:**
  - The core's transport adapter accepts an injected `requests.Session`, and legacy passes its
    `self.session`, so proxies and mounted adapters keep working.
  - `cst`, `security_token` and `token_expiry` are properties that read from the session
    manager. Their setters push values into it.
  - Overriding `_request` or `login_session` in a subclass is not supported, because they are
    private or legacy; the CHANGELOG says so.

A golden test suite pins every row of the table above against recorded HTTP fixtures.

## 8. Testing and CI
- TDD throughout.
  - Unit tests use in-memory fakes of the `HttpTransport` and `Clock` ports. They are
    deterministic, with no real sleeps.
  - The adapter is tested against recorded responses with the `responses` library.
- Contract tests run against a real **demo** account on GitHub Actions, using the repository secrets `CAPITAL_API_KEY`, `CAPITAL_IDENTIFIER` and `CAPITAL_PASSWORD` (already set). The demo host is hard-coded in these tests and cannot be overridden by any variable.
  - They are the "critical tests" and gate the merge.
  - They run on PRs from the main repository and nightly.
  - Pull requests from forks do not get the secrets, so the merge gate does not apply to them.
- CI on every PR:
  - `ruff` (lint and format check)
  - `mypy --strict`
  - `pytest` on Python 3.11 to 3.14, with coverage reported
  - Semgrep: CRITICAL and HIGH findings block the merge
  - a file-length check (300 lines or fewer)
  - an import-cycle and layering check
- Publishing: PyPI Trusted Publishing (OIDC) on a version tag. This replaces the long-lived
  `PYPI_API_TOKEN` secret.

## 9. Stages (one PR each into `master`; release only at the end)
0. Hygiene:
   - Move to the `src/` layout with the 1.0.4 code unchanged, so `master` stays releasable.
   - Add the tooling and CI gates.
   - Fix the license metadata.
   - Add `docs/adr/`.
1. Core: domain values, errors, `Result`, ports and adapters, session manager (plain login,
   keepalive, logout), rate limiter, deal confirmer. The partial-close probe drives the core
   directly on BTCUSD, sized from its dealing rules, and always closes what it opened.
2. REST resources: session extras (RSA login, account switch, `GET /session`, `/time`);
   accounts and history; positions and working orders; markets, prices, and
   sentiment; watchlists.
3. Legacy layer, golden compatibility suite, and CHANGELOG.
4. Streaming:
   - It gets its own short design addendum before any code: reconnects, token refresh, the
     40-instrument limit, and the threading model.
   - It probably needs the `websocket-client` dependency as an extra.
5. MkDocs (Material and mkdocstrings), API reference, migration guide, README rewrite, and the
   2.0.0 release.

Architecture decisions are recorded as ADRs in `docs/adr/` as they are made, not at the end.

## 10. Owner decisions (recorded)
- Backward compatibility plus a migration guide.
- Full public REST coverage. Streaming is a separate stage. MkDocs comes last.
- Typed exceptions on the public API, with `Result` internally.
- Commercial use only after consultation. Individuals trading on their own accounts may use the
  library freely.

## 11. Licensing (owner decision; implementation in stage 0)
- License: PolyForm Noncommercial 1.0.0, plus a separate commercial license from the owner on
  request.
- Additional permission grant (`LICENSE-ADDITIONAL-PERMISSION`): a natural person may use the
  software to trade their own personal accounts, demo or live, including for profit. This does
  not cover use on behalf of others, inside a business, or in a distributed or hosted product.
- `pyproject.toml` uses `license = "LicenseRef-PolyForm-Noncommercial-1.0.0"` and
  `license-files` (PEP 639). The MIT classifier is removed.
- 1.0.x carried conflicting license metadata: the license field and README said CC BY-NC 4.0,
  and the classifier said MIT. The CHANGELOG states exactly that and makes no claim about which
  one applied. The new terms apply from 2.0.0.
- The owner is advised to have a lawyer review the commercial license terms.

## 12. Calls made by the designer, open to override
- Python 3.11+.
- Staying on `requests` and a sync API.
- `Decimal` for numbers.
- Dataclasses, not pydantic.
- The new entry-point name `CapitalCom`. `Client` is avoided because of the other library's
  `getattr(..., "Client")` probing.
- RSA login as an optional extra.
- Stage order and one PR per stage.
