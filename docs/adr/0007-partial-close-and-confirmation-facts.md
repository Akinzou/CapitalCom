# 7. Partial close and other observed API behaviour

- Status: accepted
- Date: 2026-11-11

## Context

The Capital.com documentation leaves several behaviours unspecified that the library depends
on. The contract tests (`tests/contract`, run by `contract.yml` against the demo server) probe
them. Below is what the first run on 2026-11-11 observed.

## Observations

| Question | Observed on demo, 2026-11-11 | Pinned by |
|---|---|---|
| Is the confirmation `date` UTC without an offset? | Yes: `2026-11-11T17:26:11.208`, within seconds of UTC now | `test_open_and_close_are_confirmed` |
| What does `GET /confirms/{unknown}` return? | HTTP 400, `error.invalid.dealReference` (not 404) | `test_unknown_reference_is_a_pending_signal` |
| Is the confirmation's `dealId` the position id? | **No.** The position is `affectedDeals[0].dealId`; the top-level `dealId` differs and is not an open position | `test_open_and_close_are_confirmed` |
| Does `DELETE /api/v1/positions` with `{"dealId", "size"}` close part of a position? | **No.** The size is ignored: the whole position is closed (`FULLY_CLOSED`), and `GET /positions/{id}` then answers 404 `error.not-found.dealId` | `test_legacy_partial_close_endpoint_closes_the_whole_position` |
| Which key carries a rejection reason? | Not observed: no rejection happened. `reason` with a fallback to `rejectReason` stays an assumption | none yet |

## Decisions

- **Position id.** Trading calls identify the opened position by `affectedDeals[0].dealId`,
  as 1.0.4 did. Stage 2 exposes that id as the position id. The top-level `dealId` stays
  available on `DealConfirmation.deal_id`, but it is not documented as a position id.
- **Partial close.** In stage 3, legacy `close_position_by_id(deal_id, size=...)` raises
  `ValidationError` when `size` is given. Silently closing more than the caller asked for is
  the worse failure, because the caller would not notice that the position is gone. Closing a
  whole position through `DELETE /api/v1/positions/{dealId}` keeps working.
- **Pending signal.** `DealConfirmer` keeps treating both 404 and 400
  `error.invalid.dealReference` as "not ready yet". 400 is what the server sends for an
  unknown reference. 404 is still handled, so a server-side change cannot end polling early.

## Consequences

- The probes run nightly. When Capital.com changes one of these behaviours, the nightly
  contract run fails and this ADR must be revisited.
- Logins from separate clients are not spaced by any one rate limiter. When contract tests built
  a client per test, back-to-back logins drew 429 `error.too-many.requests` often enough to
  exhaust the default retries, so the contract tests now share one client for the whole run.
  An application running several clients against one account should expect the same.
