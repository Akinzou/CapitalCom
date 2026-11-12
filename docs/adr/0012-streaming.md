# 12. WebSocket streaming

- Status: accepted
- Date: 2026-11-12

## Context

Bots that react to prices poll `GET /markets` or `/prices` under a limit of 10 requests per
second. Capital.com also pushes quotes and OHLC bars over a WebSocket. The documentation
leaves several facts open: whether a stream ping keeps the REST session alive, what a refusal
looks like, how the 40-instrument limit is counted, and what happens when the session ends.
A throwaway probe on the demo server settled them before any code was written. It logged no
tokens, account ids or deal ids, and its branch was deleted afterwards.

## Probe findings (demo, 2026-11-12)

| # | Question | Observed | Consequence |
|---|---|---|---|
| P1 | Does a stream `ping` keep the REST session alive? | Yes: tokens pinged every 4 min still worked on REST after 13 min; unpinged tokens got `401` | A ping acknowledgement marks the session used |
| P2 | Do subscriptions survive a new login? | Yes; pings with the old and the new tokens both answered `OK` | No reconnect on renewal; each frame carries the current tokens |
| P3 | Which host? | `streamingHost` and `streamEndpoint` are both `wss://api-streaming-capital.backend-capital.com/` | One pinned URL for demo and live |
| P4 | What do refusals look like? | Per key inside an `OK` answer (`"ERROR: <epic> not found"`, `"ERROR: Max Subscription limit reached."`), `ALREADY_SUBSCRIBED`, `NOT_SUBSCRIBED`; whole frame `status: "ERROR"` with `errorCode`. No refusal closed the socket | Per-key checking of every acknowledgement |
| P5 | How is the limit of 40 counted? | Separately for quotes and OHLC; a 41-epic OHLC call answered two epics under their bare names | Two local limits of 40 epics; a requested key missing from the answer is a refusal |
| P6 | How often do bars come? | One `ohlc.event` per bar and per side (`bid`, `ask`), with `lastTradedVolume` | `Candle.price_side`, optional `volume`, no "closed" flag |
| P7 | What ends the stream? | Nothing within 13 min, not even `DELETE /session`; afterwards `ping` answered `error.invalid.session.token` | The keepalive is what detects a dead session |

`PUT /session` (account switch) could not be probed: the demo user has a single account.

## Decisions

### Pull iterator in the caller's thread

`cc.stream.connect()` returns a `Stream` that the caller iterates. The library starts no
thread. Receives wait until the next keepalive is due; keepalives, resubscriptions and
reconnects all run inside `next()`.

A reader thread with callbacks was rejected. An exception in a callback on a library thread
either kills the feed silently or needs an error channel the caller must remember to read.
In the pull model every error is raised where the caller iterates, and a caller who wants a
background feed runs the loop in a thread of their own. The cost is that a loop body blocking
for longer than the 5-minute keepalive delays the ping. The server keeps the socket open
(P7), so the next keepalive simply gets fresh tokens.

### The host is pinned

The URL is the constant `wss://api-streaming-capital.backend-capital.com/connect` for both
environments. The session's `streamEndpoint` is never dialled, so a changed or injected field
cannot send the session tokens to another host. The contract test asserts that the endpoint
demo reports still matches the pinned host, so drift shows up in CI.

### Layout

- `domain/streaming.py`: `Quote`, `Candle`, `Gap` and their enums. `domain/subscriptions.py`:
  the subscription set and the limits, checked before anything is sent.
- `application/ports.py`: `StreamTransport` and `StreamConnection`, since a WebSocket is a
  process boundary.
- `application/stream_frames.py` reads and writes frames. `stream_link.py` handles one
  connection: acknowledgements by correlation id, buffered events and the keepalive.
  `stream_session.py` keeps the subscription set across reconnects.
- `infrastructure/websocket_transport.py` is the only module that imports `websockets` or
  `ssl`.
- `api/stream.py` turns results into exceptions.

### Errors

- `SubscriptionError` derives from `CapitalComError`, not `ApiError`, because a WebSocket
  answer has no HTTP status. It maps each refused key to the server's text, or to `MISSING`.
- A frame refused with `error.invalid.session.token` invalidates the tokens it carried and is
  sent once more with fresh ones. A second refusal is `AuthenticationError(401)`, which
  closes the stream.
- `ResponseFormatError` is raised for a frame that is not a JSON object, or for a known event
  that lacks a field. Frames of unknown kinds are skipped and logged by kind only.
- Without the extra, `connect()` raises `ImportError` naming `capitalcom[streaming]`.

### Reconnects and gaps

- A reconnect is triggered by:
  - a dropped socket;
  - an acknowledgement or keepalive answer missing for 10 s;
  - a change of `SessionManager.current_account_id`.
- An account id of `None` means the session is between logins and does not count as a
  change.
- Backoff is 1, 2, 4, 8 and 16 s with equal jitter. After five failed attempts the stream
  raises `StreamError` (a `TransportError`), with the last failure as `__cause__`, and
  closes.
- A refused login or a refused key on resubscription is raised at once.
- After a successful resubscription the stream yields one `Gap(since, until, reason)`:
  - `since` is the local time the last event was received;
  - events read before the drop come out before the `Gap`, and events from the new
    connection after it;
  - the reason is `SERVER_CLOSED` when the server sent a close frame, `ACCOUNT_SWITCHED`
    after an account change, and `NETWORK` otherwise.
- Before an overdue keepalive answer is declared missing, frames already queued are read.
  This keeps a slow consumer on a busy feed from reconnecting every five minutes.
- Resubscription sends one quote frame plus one OHLC frame per exact set of resolutions and
  candle type. A single epics × resolutions frame would also subscribe pairs the caller had
  removed.

### `websockets`, not `websocket-client`

The `streaming` extra installs `websockets>=15`. It ships type information, so `mypy
--strict` checks the adapter, and its synchronous client has `recv(timeout=...)`, a bounded
receive queue, protocol-level keepalive and an `ssl=` context. Version 15 is the floor this
design was checked against: its synchronous client already offers all of these. Since 17.1, using `connect()` without a `with` block
is deprecated, so the adapter enters the connection through an `ExitStack`; that form works
on every supported version.

### Logs never carry a token

Every request frame contains the session tokens. The library never logs a frame. The
`websockets` logger is replaced by `capitalcom.websocket`, whose records pass through the
token-masking filter. The library's own frame dumps are dropped as well: they are cut to a
fixed length, so a token split by the cut would escape masking of the whole value.

## Consequences

- Live quotes and bars for up to 40 epics each, with every interruption visible as a `Gap`.
- The account-switch path is covered by unit tests only, until a demo user with two accounts
  is available.
- The 10-minute behaviour (P1, P7) is a probe fact, not a CI test; the contract test covers
  the host, one quote, one bar and a clean close.
