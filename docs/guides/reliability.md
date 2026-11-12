# Errors and reliability

This page is for code that trades real money. It says what each error means for an open
trade, what the library repeats on its own, what it refuses to repeat, and what you should do
next. Each guarantee names the design decision or the test that backs it.

## The exception hierarchy

Every error the library raises while talking to Capital.com derives from `CapitalComError`,
which derives from `Exception`
([ADR 0005](../adr/0005-error-model.md)). Three things are raised outside it, each before
anything is sent: the `CapitalCom` constructor raises `ValueError` for an empty API key,
identifier or password; a missing extra raises `ImportError` naming it; and
`positions.amend` or `orders.amend` without one of their required keyword arguments raises
`TypeError` (`tests/unit/api/test_facade.py`, `tests/unit/api/test_stream.py`,
`tests/unit/api/test_positions.py`, `tests/unit/api/test_orders.py`).

- `CapitalComError`
    - `ValidationError`
    - `ApiError`, with `status`, `error_code` and `body`
        - `AuthenticationError`
        - `NotFoundError`
        - `RateLimitError`
        - `ResponseFormatError`
    - `TransportError`
        - `StreamError`
    - `SubscriptionError`
    - `OutcomeUnknownError`
    - `DealRejectedError`
    - `ConfirmationTimeoutError`
    - `SizeAdjustedError`

What each one means when it comes out of a trade call (`positions.open`, `amend`, `close`,
and the same on `cc.orders`):

| Error | Meaning | What it tells you about the trade |
|---|---|---|
| `ValidationError` | A rule checked locally failed | Nothing was sent |
| `AuthenticationError` | HTTP 401, still, after one fresh login and one resend | Refused before acting |
| `RateLimitError` | HTTP 429 after every allowed retry; `retry_after` holds the server's wait | Refused before acting |
| `NotFoundError` | HTTP 404 | Answered with an error; no deal reference came back |
| `ApiError` (other) | Another 4xx answer; `status` and `error_code` say which | Answered with an error; no deal reference came back |
| `ResponseFormatError` | The login before the trade answered without the documented shape | The trade request was not sent |
| `TransportError` | A connect timeout on the trade request, or the login before it failed | The trade request was not sent |
| `OutcomeUnknownError` | Sent, with no usable answer | May exist |
| `DealRejectedError` | The confirmation says `REJECTED`; `reason` says why | Not made |
| `ConfirmationTimeoutError` | No final confirmation within `confirm_timeout` | May exist |
| `SizeAdjustedError` | Booked with a size other than the one requested | Booked |

Sources: [ADR 0005](../adr/0005-error-model.md),
[ADR 0006](../adr/0006-retries-and-idempotency.md), [ADR 0010](../adr/0010-trading.md),
`tests/unit/application/test_dispatcher.py`, `tests/unit/application/test_confirmer.py`,
`tests/unit/api/test_positions.py`.

- 429 and 401 are refused by the server before it acts, which is why the library may resend
  even a trade after them ([ADR 0006](../adr/0006-retries-and-idempotency.md)).
- A trade answered with a success status whose body cannot be read, or that carries no deal
  reference, raises `OutcomeUnknownError` with the `ResponseFormatError` as its cause: the
  server took the request, so the deal may exist (`tests/unit/api/test_positions.py`).
- `ConfirmationTimeoutError` is not a subclass of `OutcomeUnknownError`; catch both
  (`src/capitalcom/domain/errors.py`).
- `StreamError` is a `TransportError` raised by a stream that gave up reconnecting, and
  `SubscriptionError` is a refused stream subscription; neither involves a trade
  ([ADR 0012](../adr/0012-streaming.md)).
- Errors pickle from their constructor arguments, so they cross `multiprocessing` and
  `concurrent.futures` (`tests/unit/domain/test_errors_secret_enums.py`).

## What the library retries, and what it does not

Only reads and the session calls (login, logout, account switch) are repeated after a
failure that may have reached the server. A DELETE closes a
position and a PUT amends one, so repeating either after a lost answer can act on a different
state ([ADR 0006](../adr/0006-retries-and-idempotency.md)).

| Outcome | GET, login, logout, account switch | Other POST / PUT / DELETE |
|---|---|---|
| 429 | retried | retried |
| 429 with `Retry-After` over 60 s | `RateLimitError` at once | `RateLimitError` at once |
| 401 on a call made with a session | one fresh login, one resend | one fresh login, one resend |
| 502, 503, 504 | retried | `OutcomeUnknownError` |
| other 5xx | `ApiError` | `OutcomeUnknownError` |
| connect timeout | retried | `TransportError` |
| any other network or TLS failure | retried | `OutcomeUnknownError` |
| other 4xx | mapped error | mapped error |

A repeated logout is answered 401, which counts as logged out. Sources:
[ADR 0006](../adr/0006-retries-and-idempotency.md),
`tests/unit/application/test_dispatcher.py` and
`tests/unit/application/test_session_api_client.py`.

- The default `RetryPolicy(max_attempts=3, base_delay_s=0.5, max_delay_s=8.0)` sends a
  retryable request at most three times. The wait doubles from the base up to the cap, and
  half of each wait is random. A `Retry-After` header replaces that wait
  (`tests/unit/application/test_retry_rate_limiter.py`).
- Pass `retry=RetryPolicy(...)` to `CapitalCom` to change it. When retries run out, the last
  attempt's error is raised ([ADR 0006](../adr/0006-retries-and-idempotency.md)).
- `OutcomeUnknownError` can come from any call that is not a read, not only from trades:
  watchlist changes, `accounts.update_preferences` and `accounts.top_up` follow the same
  column ([ADR 0006](../adr/0006-retries-and-idempotency.md)).
- After a deal is submitted, any failure while waiting for its confirmation, other than
  "not ready yet", becomes `OutcomeUnknownError` with the cause chained, never the raw error
  of the poll (`tests/unit/application/test_confirmer.py`).

## Recipes

```python
--8<-- "docs/examples/errors.py:deal"
```

**`OutcomeUnknownError`.** The request was sent and the deal may exist. Do not send it again
until you have looked: read `cc.positions.list()` and `cc.orders.list()`, and send again
only if the deal is not there. The library never guesses for you
([ADR 0006](../adr/0006-retries-and-idempotency.md)).

**`ConfirmationTimeoutError`.** The deal was submitted and got a deal reference, but no final
confirmation arrived before `confirm_timeout` (5 seconds by default) ran out, and it may
still execute. Look exactly as for `OutcomeUnknownError`; it is not a subclass of it, which
is why the recipe catches both in one branch (`tests/unit/docs/test_examples.py`). `error.deal_reference` names the
submission in your logs (`tests/unit/application/test_confirmer.py`).

**`SizeAdjustedError`.** The server rounded the size and booked the deal.
`error.confirmation` is the confirmation of the deal as booked, and `error.requested` is the
size you asked for. Close the position with `cc.positions.close(error.confirmation.position_id)`,
when it is not `None`, or keep it at the booked `error.confirmation.size`. For a working
order the id is `error.confirmation.deal_id`. Pass `instrument=` to catch an
off-grid size before sending ([ADR 0010](../adr/0010-trading.md)).

**`DealRejectedError`.** The server confirmed that no deal was made; `error.reason` carries its
reason, such as `RC_NOT_ENOUGH_MARGIN` in the observed case. Fix the cause before sending
again ([ADR 0007](../adr/0007-partial-close-and-confirmation-facts.md),
[ADR 0010](../adr/0010-trading.md)).

Local checks raise before anything is sent:

```python
--8<-- "docs/examples/errors.py:validation"
```

A `Decimal` with more than 15 significant digits raises `ValidationError` instead of being
rounded by the server to a size or level you did not ask for. The body is checked before a
rate-limit slot is spent ([ADR 0005](../adr/0005-error-model.md),
`tests/unit/application/test_dispatcher.py`).

## Timeouts

- `timeout=(5.0, 15.0)` on `CapitalCom` is the connect and read timeout of each HTTP request,
  in seconds (`src/capitalcom/api/client.py`).
- A connect timeout means the request never left: a trade raises `TransportError`. A read
  timeout may come after the server acted: a trade raises `OutcomeUnknownError`
  (`tests/unit/infrastructure/test_adapters.py`, `tests/unit/application/test_dispatcher.py`).
- `confirm_timeout=5.0` is how long the client keeps polling for a deal confirmation, every
  0.1 s: no new poll starts after it. A poll already in flight still runs to its own HTTP
  timeout and retries, so the call can take longer. Even a zero timeout asks once
  (`src/capitalcom/application/confirmer.py`, `tests/unit/application/test_confirmer.py`).

## Rate limits and 429

Capital.com publishes three limits, and the library holds every request back until it fits
all that apply: 10 requests in any second, one `POST /positions` or `POST /workingorders` in
any 0.1 s, and one login in any second. The calling thread waits; nothing is raised
([ADR 0006](../adr/0006-retries-and-idempotency.md),
`tests/unit/application/test_retry_rate_limiter.py`).

The server can still answer 429. It is retried with the backoff above, honouring
`Retry-After` up to 60 s; a longer `Retry-After` raises `RateLimitError` at once, so a bot
does not freeze silently. `RateLimitError.retry_after` holds the server's value
(`tests/unit/application/test_dispatcher.py`).

The limits are counted per `CapitalCom` instance. Logins from several clients on one account
are not spaced against each other, and back-to-back logins drew 429 often enough to exhaust
the default retries ([ADR 0007](../adr/0007-partial-close-and-confirmation-facts.md)).

## Session renewal

- The first call logs in. A session idle for 570 seconds is renewed before the next request,
  because the server ends it at 600 (`tests/unit/application/test_session_api_client.py`).
- A 401 answer causes one fresh login and one resend; a second 401 raises
  `AuthenticationError` instead of looping (`tests/unit/application/test_session_api_client.py`).
- After `cc.session.switch_account`, every renewal returns to the chosen account before any
  token is used, or fails ([ADR 0008](../adr/0008-session-context-and-read-models.md)).
- A closed client raises `CapitalComError` instead of logging in again
  (`tests/unit/api/test_facade.py`).

## TLS

- Certificates are always verified. A `requests.Session` passed as `http_session` with
  `verify=False` cannot switch verification off, and redirects are never followed, because
  `requests` would resend the session tokens to the redirect target
  (`tests/unit/infrastructure/test_adapters.py`).
- The base URL must be `https://` (`tests/unit/infrastructure/test_adapters.py`).
- The stream refuses to switch verification off and dials one pinned `wss` host, never the
  endpoint the session reports ([ADR 0012](../adr/0012-streaming.md),
  `tests/unit/infrastructure/test_websocket_transport.py`).
- Behind a proxy that re-signs TLS, pass an `http_session` whose `verify` is the path of the
  proxy's CA bundle; REST requests keep that path
  (`tests/unit/infrastructure/test_adapters.py`).
- The stream trusts the same CA bundle as REST: the session's `verify` path first, then the
  `REQUESTS_CA_BUNDLE` and `CURL_CA_BUNDLE` environment variables when the session trusts
  the environment; without any of them it uses the bundle `requests` ships with ([ADR 0012](../adr/0012-streaming.md),
  `tests/unit/api/test_stream.py`).

## Secrets in logs and errors

- The library logs under `capitalcom` and never configures logging; it only adds a
  `NullHandler` (`src/capitalcom/application/logs.py`).
- The API key, the password and every session token are replaced by `***` in the records of
  the library's loggers (`tests/unit/application/test_result_ports_codec.py`).
- A path in a log record shows the resource, not the deal: `/api/v1/positions/{id}` stands
  for a position, order, confirmation or watchlist id
  (`tests/unit/application/test_dispatcher.py`). Error messages do keep the deal reference,
  so you can find the deal they are about.
- The identifier (your login) is not on the masking list. It is kept out of `repr`, which
  shows only the environment (`tests/unit/api/test_facade.py`).
- Error messages never contain request headers or bodies. A network error names only the
  method and path, and an `ApiError` keeps at most 500 characters of the response body ([ADR 0005](../adr/0005-error-model.md),
  `tests/unit/infrastructure/test_adapters.py`).
- Stream frames are never logged, and the WebSocket library emits no DEBUG record
  ([ADR 0012](../adr/0012-streaming.md),
  `tests/unit/infrastructure/test_websocket_transport.py`).

## Threads

When several threads share one `CapitalCom`, the library guarantees:

- threads that find an expired session cause one login, not one each
  ([ADR 0006](../adr/0006-retries-and-idempotency.md),
  `tests/unit/application/test_session_api_client.py`);
- the rate limiter books send times under one lock, in order, so two threads never share a
  slot (`tests/unit/application/test_retry_rate_limiter.py`);
- requests already in flight on other threads during `cc.session.switch_account` may run on
  either account, so switch before starting work on an account, not while trading
  ([ADR 0008](../adr/0008-session-context-and-read-models.md)).

A `Stream` is used from one thread. A call from a second thread while another is in progress
raises `ValidationError`. `close()` is the exception: it may come from any thread, and the
loop reading the stream then ends instead of reconnecting
([ADR 0012](../adr/0012-streaming.md), `tests/unit/application/test_stream_gaps.py`,
`tests/unit/api/test_stream.py`). One `CapitalCom` holds at most one open stream
(`tests/unit/api/test_stream.py`).
