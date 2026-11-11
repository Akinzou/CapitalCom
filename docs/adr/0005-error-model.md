# 5. Error model

- Status: accepted
- Date: 2026-11-11

## Context

Inside the library, every call that crosses the network can fail in several expected ways, and
the services must decide between retrying, re-authenticating, polling or giving up. Callers of
a Python library, on the other hand, expect exceptions, and 1.x code catches `Exception`.

## Decision

- **Result inside, exceptions outside.** Ports and application services return
  `Ok(value) | Err(error)`. Only the public facade (`capitalcom.api`) calls `unwrap()`, which
  raises the carried error. A failure therefore cannot be dropped silently between layers: the
  type checker forces every caller to handle the `Err` branch.
- **One hierarchy.** Every error derives from `CapitalComError(Exception)`, so
  `except Exception` in 1.x code keeps working.
- **Server errors subclass `ApiError`.** `AuthenticationError` (401), `NotFoundError` (404),
  `RateLimitError` (429, with `retry_after`) and `ResponseFormatError` (a response without the
  documented shape) all carry `status`, `error_code` (Capital.com's `errorCode`, or `None`)
  and `body` (cut to 500 characters). One `except ApiError` handles every server-side refusal,
  and a specific subclass can still be caught on its own.
- **Unknown outcome is its own error.** A timeout or 5xx after a non-GET request was sent
  raises `OutcomeUnknownError`, never a retry: the trade may have executed.
- **Decimal on the wire.** Amounts are `Decimal` in the API. JSON numbers are doubles on the
  server, so a `Decimal` with more than 15 significant digits raises `ValidationError` before
  sending instead of being rounded to a size or level the caller did not ask for.
- **Errors pickle** from their constructor arguments, so they survive `multiprocessing` and
  `concurrent.futures`.

## Consequences

- Internal code reads as explicit branching on `Err`; public code reads as normal Python.
- Messages never contain request headers or bodies, so tokens and passwords cannot reach a
  traceback through an error.
