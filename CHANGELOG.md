# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **`OutcomeUnknownError` always says why.** After a network failure that followed the send,
  or a 5xx answer to a trade or another change, the error now carries that failure as its
  `__cause__`, shown in the traceback, as the other cases already did.

### Documentation

- The streaming guide says that the stream stays open after `ResponseFormatError`, so a
  reader catches it and keeps reading.

## [2.0.0] — 2026-11-12

### Added

- **`CapitalCom`, the 2.x client** (`from capitalcom import CapitalCom`). It logs in lazily,
  renews the session before Capital.com's 10-minute idle timeout, and logs out on `close()` or
  at the end of a `with` block. Namespaces: `session`, `accounts`, `history`, `positions`,
  `orders`, `markets`, `prices`, `sentiment` and `watchlists`.
- **Live prices over the WebSocket** (`cc.stream`, needs `pip install "capitalcom[streaming]"`).
  `with cc.stream.connect() as stream:` opens the stream; `subscribe_quotes` and
  `subscribe_ohlc` add up to 40 epics each, and iterating yields `Quote`, `Candle` and `Gap`
  events in the calling thread. The stream keeps the session alive, reconnects with backoff,
  resubscribes, and reports every interruption as a `Gap`. It raises `SubscriptionError` for
  a refused key and `StreamError` when it gives up. TLS is always verified and the host is
  fixed by the library.
- **Documentation site** at <https://akinzou.github.io/CapitalCom/>: getting started, guides,
  an errors and reliability page, the API reference and the design decisions. Its code
  examples are files the test suite runs, and the README quick start is one of them.
- **Migration guide** in `docs/guides/migration.md` (on the documentation site), mapping
  every 1.x call to its 2.x equivalent.
- **Typed errors.** Every error derives from `CapitalComError` (and from `Exception`).
  Server refusals are `ApiError` subclasses that carry `status` and `error_code`. A trade
  whose outcome is unknown after a timeout raises `OutcomeUnknownError` instead of being
  retried.
- **Safe transport.** Every request has connect and read timeouts. TLS verification cannot be
  switched off (a CA bundle path set on an injected session is honoured, for TLS-inspecting
  proxies), redirects are not followed, and requests are throttled to Capital.com's
  published limits. `429` responses are retried with backoff and `Retry-After`.
- **Precise numbers.** Prices, sizes and amounts are `Decimal`, and timestamps are aware UTC
  `datetime` values.
- **Redacted logs.** The library logs under `capitalcom` with a `NullHandler`, and masks the
  API key, password and session tokens in its own log records.

### Changed

- **Licence.** 1.0.x carried conflicting licence metadata: the licence field and the README
  said CC BY-NC 4.0, and the package classifier said MIT. From 2.0.0 the terms are the
  PolyForm Noncommercial License 1.0.0 (`LICENSE`) plus the additional permission for personal
  trading in `LICENSE-ADDITIONAL-PERMISSION`. Commercial licences are available on request.
- **Python support.** Python 3.11 or newer is required. Python 3.8–3.10 are no longer
  supported.
- **Dependencies.** `requests>=2.32.4` is required.

### Deprecated

- **`CapitalClient`, the 1.x API.** It keeps its 1.0.4 signatures and return values and runs
  on the 2.x core. Each of its names emits one `DeprecationWarning` per process. It will be
  removed no earlier than 3.0.

### Changed in `CapitalClient` (deliberately; ADR 0011)

1. **Logging.** Importing the library no longer calls `logging.basicConfig`, and log
   messages carry no ANSI colour codes. `colored_log` logs under `capitalcom.client`.
2. **Closing.**
   - A full close uses the documented `DELETE /positions/{dealId}` and waits for the
     confirmation. A rejected close now raises instead of returning `"SUCCESS"`.
   - `close_position_by_id` and `close_position_by_ref` with a non-zero `size` raise
     `ValidationError` before sending anything: Capital.com closes the whole position
     whatever size is sent.
   - `size=0` still closes the whole position.
3. **Typed errors.** Errors are subclasses of `CapitalComError`, which derives from
   `Exception`, instead of bare `Exception`. Examples are `AuthenticationError`, `ApiError`
   and `NotFoundError`; "No accounts found." is a `CapitalComError`. Network failures are
   `TransportError`s that are also `requests.exceptions.ConnectionError`, so existing
   `except requests.exceptions.ConnectionError` and `except RequestException` clauses still
   catch them; a trade whose outcome is unknown is not one of them (change 5).
4. **Rejected opens raise.** A rejected open raises `DealRejectedError`, with the server's
   reason. A rejected confirmation names no affected deal, so 1.0.4 asked for it ten more
   times and then raised a bare `Exception` saying the deal reference was not resolved.
5. **Timeouts.**
   - Every request has a timeout.
   - A trade request that times out raises `OutcomeUnknownError` and is never resent.
   - In 1.0.4 such a call could hang forever.
6. **`test_trade` closes its position by id.** 1.0.4 looked the dealId up as a deal
   reference, which could leave the test position open.
7. **Read-only names.**
   - `api_key`, `login`, `password`, `session` and `base_url` are read-only, and assigning
     one raises `AttributeError`.
   - `cst`, `security_token` and `token_expiry` still accept assignment.
8. **`_request`.** It always verifies TLS and never follows redirects: `verify=False` or
   `allow_redirects=True` raises `ValidationError`, while `verify=<CA bundle path>` and a
   path set on `client.session.verify` still work. A path that does not start with a single
   `/` raises too, so the session tokens cannot be sent to another host. The first `401`
   gets one re-login and one resend even when it follows a `429` (1.0.4 re-logged in only
   on the very first attempt), and a second `401` is returned as before.
9. **Narrower exports.** `from capitalcom import *` no longer re-exports the `requests`,
   `time`, `logging` and `random` modules. `capitalcom.client.time` and
   `capitalcom.client.random` still exist, so `mock.patch("capitalcom.client.time.sleep")`
   keeps working.
10. **Top-up result.** `top_up_demo` raises `ApiError` when the server answers
    `"successful": false`.
11. **Opens that open nothing.** An open that nets against an existing position raises
    `CapitalComError` saying no position was opened. 1.0.4 also raised, after its retries.
    A size the server rounded is logged as a warning.
12. **Overriding is narrower.** The public methods still call each other through `self`, as in
    1.0.4. Overriding `_request` or `login_session` in a subclass no longer changes how they
    reach the server, and the constructor no longer calls `login_session`.

### Fixed

Found while preparing this release, before any 2.x version shipped; each entry is listed because
it settles a behaviour you can rely on.

- **Request bursts.** More than 10 requests in one second now wait for the window to free up
  instead of drawing a `429`. The limits are counted as sliding windows at send time (ADR 0006).
- **Clearer format errors.** An account preference without the leverage in force says the field
  is missing instead of "expected an integer, got NoneType", and a malformed
  `currentAccountId` in a login answer names the field and what is wrong with it.
- **Malformed stream frames.** A frame that cannot be decoded no longer aborts a subscribe or
  closes the stream during a reconnect. It is raised as `ResponseFormatError` at its position
  among the events, and iteration may go on. If the unreadable frame was the awaited
  acknowledgement itself, the wait times out into a reconnect and a `NETWORK` gap.
- **Events before a give-up.** When the stream gives up (five failed reconnects, or a login or
  key refused while resubscribing), the events it had already read are no longer lost.
  Inside `next()` they come first, then the error, then iteration ends. If a subscribe call
  raised the error, iteration yields the events and ends without raising it again.
  `stream.closed` is `True` at once, so `cc.stream.connect()` may open a new stream.
  `close()` still drops what was not read.
- **Gap reasons.** A gap is `SERVER_CLOSED` only when the server started the close, and
  `NETWORK` when our side did. A drop after the session moved to another account, even one
  switched from another thread, is `ACCOUNT_SWITCHED`.
- **Type checkers.** The package ships a `py.typed` marker, so a type checker reads its
  annotations instead of treating it as untyped, and `from capitalcom import CapitalCom` (and
  every other 2.x name) is an explicit re-export, which `mypy --strict` requires.
- **A trade answer that cannot be read.** A trade the server answered with success but with
  a body that is not JSON, or with no deal reference, raises `OutcomeUnknownError` (the
  parse error is its cause) instead of `ResponseFormatError`: the deal may exist. The same
  holds for watchlist changes, preferences and top-ups; login, logout and account switches
  keep `ResponseFormatError` (ADR 0006).
- **Stream CA bundle.** The stream trusts the same CA bundle as REST: a bundle path on the
  session now beats `REQUESTS_CA_BUNDLE`, as it always did for REST (ADR 0012).
- **Ids in logs.** Retry and rate-limit log records show `/api/v1/positions/{id}` instead of
  the deal, order, confirmation or watchlist id.
- **Deprecation link.** The `CapitalClient` deprecation warning points to the migration guide
  on the documentation site.

[Unreleased]: https://github.com/Akinzou/CapitalCom/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/Akinzou/CapitalCom/releases/tag/v2.0.0
