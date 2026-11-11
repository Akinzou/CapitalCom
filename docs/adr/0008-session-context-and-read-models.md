# 8. Session context and read models

- Status: accepted
- Date: 2026-11-11

## Context

Stage 2a adds the rest of the session API, `cc.accounts` and `cc.history`. The new pieces raise
four questions:

- how a selected account survives the automatic re-logins of stage 1;
- where RSA password encryption lives when its library is optional;
- how `/time` is called;
- how strictly server payloads are read.

## Decisions

### The selected account is re-applied after every re-login

A fresh `POST /session` always lands on the account the server treats as default. The
session manager renews a session silently, either after 570 s idle or after a 401. If it
forgot a switch, a bot that switched to account B would keep trading on account A after the
next renewal, with no error.

The manager therefore stores the account the caller selected. After each login, still
holding the login lock, it compares that account with the body's `currentAccountId`. If they
differ, it sends `PUT /session` before handing out any token. If that switch fails, the new
tokens are dropped and the error is returned. No caller ever receives a token for the wrong
account. A login body without `currentAccountId` is a `ResponseFormatError`, because the
comparison cannot be made without it.

`PUT /session` is sent through the dispatcher, not `ApiClient`, because `ApiClient` keeps only
the body. If the answer carries `CST` and `X-SECURITY-TOKEN`, they replace the session tokens.

`PUT /session` is retry-safe (ADR 0006). A retry after a lost response can therefore reach a
session that has already switched, and the server answers it with a 400. That 400 has the
code `SWITCH_ALREADY_ACTIVE` and is treated as success. A contract probe pins the code.

Requests already in flight on other threads during a switch may run on either account. This
is documented on `cc.session.switch_account` rather than prevented: preventing it would mean
holding every request behind the switch.

### RSA encryption is an injected function, not a port

Encrypting the password crosses no process boundary, so it is not a port. It lives in
`infrastructure/rsa_password.py` for one reason: it needs `cryptography`, a third-party and
optional dependency (`capitalcom[encryption]`) that the core's import allowlist forbids.

`SessionManager` receives the function as a `PasswordEncryptor`. The composition root
imports it only when `encrypted_password=True`. A missing extra therefore fails in the
`CapitalCom` constructor with an install hint, not at the first trade.

Every login fetches a fresh key, renewals included, because the ciphertext embeds the
server's timestamp.

Capital.com documents the scheme only through a Java sample:

- base64 of `password|timeStamp`;
- RSA with PKCS#1 v1.5 padding, using the DER SubjectPublicKeyInfo key;
- base64 of the ciphertext.

The sample's prose says "AES", but the code it shows uses RSA. The padding and the UTF-8
charset follow Java's defaults. `test_encrypted_password_login` checks them against the demo
server.

### `/time` is called without a session

`GET /api/v1/time` needs no authentication. `cc.session.server_time()` therefore sends it
through the dispatcher directly. Checking clock drift never costs a rate-limited login.

### Read models

Read models are frozen dataclasses built by `from_api` with the strict converters in
`domain/parsing.py`. A missing field, or a field with the wrong JSON type, raises
`ResponseFormatError` naming the field. Money and sizes are `Decimal`, and leverages are
`int`. Every model keeps the full payload in `raw`.

Server enumerations stay `str`: status, type, source and account type. Capital.com adds values
over time, and a listing must not fail because one row carries a value this version does not
know. Caller inputs become enums only where the documented set is closed.

Only UTC timestamp fields are parsed into `datetime`: `dateUTC`, `dateUtc`, and epoch
milliseconds. The local-time fields stay in `raw`, because their zone is the account's and is
not stated in the payload.

Query datetimes must be timezone-aware. They are sent in UTC as `YYYY-MM-DDTHH:MM:SS`. A naive
datetime raises `ValidationError`, because guessing between the machine's zone and UTC would
silently shift the window by hours.

The documented history limits are checked before sending:

- a span of at most one day for activity;
- `last_period` not combined with dates;
- `start <= end`;
- whole seconds.

`accounts.top_up` refuses `Environment.LIVE` locally.

## Consequences

- Switching accounts is safe across renewals. The cost is that one renewal may take two
  requests instead of one.
- Plain-password users never import `cryptography`. The `dev` dependency group installs it,
  so CI type-checks and tests the encrypted path.
- A new server enum value never breaks a read. Callers who need exhaustive handling compare
  strings themselves.
- Contract probes pin `SWITCH_ALREADY_ACTIVE` and the RSA details. If a probe fails, change the
  constant or the implementation together with its unit test, and update this ADR.
