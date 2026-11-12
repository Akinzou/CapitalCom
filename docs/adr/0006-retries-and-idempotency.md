# 6. Retries, idempotency and rate limits

- Status: accepted
- Date: 2026-11-11

## Context

Trading bots run unattended. A client that retries too eagerly opens duplicate positions; one
that never retries fails on every transient network blip. Capital.com publishes request limits:
10 requests per second overall, one `POST /positions` or `POST /workingorders` per 0.1 s, and
one session creation per second.

## Decision

Retry matrix (`Dispatcher`, default `RetryPolicy(max_attempts=3, base_delay_s=0.5,
max_delay_s=8.0)`):

Login and logout (`POST`/`DELETE /api/v1/session`) follow the GET column: a repeated login only
issues new tokens, and a repeated logout is answered 401, which logout treats as done.

| Outcome | GET (and session calls) | other POST / PUT / DELETE |
|---|---|---|
| 2xx | done | done |
| 429 | retry | retry (refused before acting) |
| 429 with `Retry-After` > 60 s | `RateLimitError` at once | `RateLimitError` at once |
| 401 | re-login once, resend | re-login once, resend (refused before acting) |
| 502 / 503 / 504 | retry | `OutcomeUnknownError`, no retry |
| other 5xx | `ApiError`, no retry | `OutcomeUnknownError`, no retry |
| connect timeout | retry | `TransportError`, no retry (never sent) |
| any other transport failure, TLS errors included | retry | `OutcomeUnknownError`, no retry |
| other 4xx | mapped error, no retry | mapped error, no retry |

- Only GET counts as idempotent. A DELETE closes a position and a PUT amends one; repeating
  either after a lost response can act on a different state.
- Backoff is exponential with equal jitter, capped at `max_delay_s`. `Retry-After` (seconds or
  an HTTP-date) wins when present, capped at 60 s.
- When retries run out, the last attempt's error is returned.
- TLS errors count as "may have been sent": `requests` raises the same `SSLError` for a failed
  handshake and for a connection dropped while the response was read.
- Once a deal is submitted, any failure while polling `/confirms` other than "not ready yet"
  becomes `OutcomeUnknownError` (with the cause chained), never the raw poll error.
- A request body that cannot be encoded exactly fails with `ValidationError` before a
  rate-limit slot is spent.
- Rate limiting is client-side sliding windows: GENERAL (10 sends in any 1 s), TRADE (1 in any
  0.1 s) and SESSION (1 in any 1 s). Token buckets were replaced in 2.0.0: a bucket of capacity
  10 refilling at 10/s let about 19 requests out in the first second, more than the server
  allows. Under a lock, a request books the earliest time valid in every window it belongs to
  and records that same time in all of them, so a login delayed by SESSION counts in GENERAL
  when it is really sent. Times are booked in order per window (FIFO), and the caller sleeps
  outside the lock, so concurrent threads queue in order.
- Session tokens are renewed after 570 s idle (the server expires them at 600 s). One lock
  covers check-and-login, so threads that find an expired session cause one login.

## Consequences

- A caller who sees `OutcomeUnknownError` must check positions before resending; the library
  will not guess.
- Waiting always goes through the `Clock` port, so every rule above is tested without sleeping.
