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

| Outcome | GET | POST / PUT / DELETE |
|---|---|---|
| 2xx | done | done |
| 429 | retry | retry (refused before acting) |
| 401 | re-login once, resend | re-login once, resend (refused before acting) |
| 502 / 503 / 504 | retry | `OutcomeUnknownError`, no retry |
| other 5xx | `ApiError`, no retry | `OutcomeUnknownError`, no retry |
| connect timeout / TLS failure | retry | `TransportError`, no retry (never sent) |
| any other transport failure | retry | `OutcomeUnknownError`, no retry |
| other 4xx | mapped error, no retry | mapped error, no retry |

- Only GET counts as idempotent. A DELETE closes a position and a PUT amends one; repeating
  either after a lost response can act on a different state.
- Backoff is exponential with equal jitter, capped at `max_delay_s`. `Retry-After` (seconds or
  an HTTP-date) wins when present, capped at 60 s.
- When retries run out, the last attempt's error is returned.
- Rate limiting is client-side token buckets: GENERAL (10/s, burst 10), TRADE (10/s, burst 1)
  and SESSION (1/s, burst 1). A request reserves a slot in every bucket it belongs to under a
  lock and sleeps outside it, so concurrent threads queue in order.
- Session tokens are renewed after 570 s idle (the server expires them at 600 s). One lock
  covers check-and-login, so threads that find an expired session cause one login.

## Consequences

- A caller who sees `OutcomeUnknownError` must check positions before resending; the library
  will not guess.
- Waiting always goes through the `Clock` port, so every rule above is tested without sleeping.
