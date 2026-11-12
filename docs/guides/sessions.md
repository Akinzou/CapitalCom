# Sessions and accounts

## Logging in

`CapitalCom` does not log in when it is constructed. The first call that needs a session
logs in, and later calls reuse it:

```python
--8<-- "docs/examples/sessions.py:client"
```

The constructor only checks that the API key, identifier and password are not empty; it
raises `ValueError` otherwise. Wrong credentials therefore surface at the first call, not
in the constructor.

With `encrypted_password=True` the password is sent encrypted with a key the server issues
for each login. It needs the `encryption` extra (`pip install "capitalcom[encryption]"`);
without it the constructor raises `ImportError`
([ADR 0008](../adr/0008-session-context-and-read-models.md)).

## Ending the session

`cc.close()` closes an open stream, logs out and releases the HTTP connections the client
created; a `requests.Session` you passed as `http_session` stays open. `with
CapitalCom(...) as cc:` calls it when the block ends. After `close()`:

- a call that needs a session raises `CapitalComError` instead of logging in again;
- a second `close()` does nothing.

If logging out fails, `close()` raises the error. When the `with` block is already leaving
because of an exception, a failed logout is logged as a warning instead, so the exception
you see is the one from your block.

`cc.session.logout()` ends the session without closing the client: the next call logs in
again.

## Renewal

Capital.com ends a session after 10 minutes without use. The client renews it before the
next request once it has been idle for 570 seconds, and answers a `401` with one fresh login
and one resend. You do not call anything to keep it alive between calls
([ADR 0006](../adr/0006-retries-and-idempotency.md)).

`cc.session.ping()` sends `GET /api/v1/ping`, which checks connectivity and counts as use of
the session. A stream you are iterating keeps the session alive with its own keepalive
([ADR 0012](../adr/0012-streaming.md)).

Two other session calls:

- `cc.session.info()` returns a `SessionInfo` with the client id, the account id, currency,
  locale, timezone offset and streaming endpoint of the live session.
- `cc.session.server_time()` returns the server clock as a UTC `datetime`. It needs no
  session, so it never logs in.

## Accounts

```python
--8<-- "docs/examples/sessions.py:accounts"
```

`cc.accounts.list()` returns every account of the login as `Account` objects. Money is
`Decimal`: `account.balance` has `balance`, `deposit`, `profit_loss` and `available`.

- `cc.accounts.preferences()` returns the hedging mode and the leverage per instrument
  class.
- `cc.accounts.update_preferences(leverages=..., hedging_mode=...)` sends only the arguments
  given; calling it with neither raises `ValidationError`.
- `cc.accounts.top_up(amount)` changes the balance of a demo account. On `Environment.LIVE`
  it raises `ValidationError` without sending anything.

Values the server enumerates, such as `account_type` and `status`, stay strings, so a value
Capital.com adds later does not break a read
([ADR 0008](../adr/0008-session-context-and-read-models.md)).

## Switching account

A login lands on the account the server treats as default.
`cc.session.switch_account(account_id)` moves the session to another account of the same
login. The client remembers the choice: every later automatic re-login switches back to that
account before any request uses the new session, and if that switch fails, the error is
raised instead of a request going to the default account
([ADR 0008](../adr/0008-session-context-and-read-models.md)).

!!! warning
    Requests already in flight on other threads while the switch happens may run on either
    account. Switch before starting work on an account, not while trading on another.

The demo login the contract tests use has a single account, so the switch between two
accounts is covered by unit tests only
([ADR 0008](../adr/0008-session-context-and-read-models.md)).

## History

```python
--8<-- "docs/examples/sessions.py:history"
```

`cc.history.activity(...)` returns account events, and `cc.history.transactions(...)` money
movements. Both take a window as `last_period` (a `timedelta`), as `start` and `end`, or
not at all:

- `start` and `end` must be timezone-aware; a naive `datetime` raises `ValidationError`,
  because guessing between the machine's zone and UTC would shift the window by hours;
- `last_period` cannot be combined with `start` or `end`, and must be a whole number of
  seconds;
- `start` must not be after `end`;
- `activity` covers at most one day, by either form; `transactions` has no such limit.

`activity` also takes `detailed=True`, `deal_id=` and a FIQL filter as `fiql=`, for example
`"epic==SILVER;status==ACCEPTED"`. `transactions` takes `transaction_type=`, for example
`"TRADE"`. Each rule is checked before anything is sent
([ADR 0008](../adr/0008-session-context-and-read-models.md)).

Only UTC timestamps are parsed into `datetime`. Fields in the account's local time stay in
each row's `raw` payload, because their zone is not stated.
