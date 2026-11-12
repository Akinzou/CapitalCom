# capitalcom 2.0 — Streaming addendum (stage 4)

Status: approved by owner 2026-11-12, probe findings in §3 · Date: 2026-11-12 · Branch: `rewrite/stage-4-streaming`
Extends `2026-11-11-capitalcom-v2-design.md` (goal 6, §9 stage 4). Where the two disagree,
this document wins for streaming only.

## 1. Intent

Bots that react to prices today poll `GET /markets` or `/prices` under a 10 requests/s limit.
Capital.com also pushes quotes and OHLC bars over a WebSocket. Stage 4 exposes that push
feed through the same `CapitalCom` client. It reuses the same login and the same errors, and
it holds to the same rule as the REST core: nothing fails silently.

## 2. What the documentation says (open-api.capital.com, read 2026-11-12)

- One URL: `wss://api-streaming-capital.backend-capital.com/connect`.
- Every client message is JSON with `destination`, `correlationId`, `cst`, `securityToken`
  and, except for `ping`, a `payload`. The session tokens travel in every frame.
- Destinations:
  - `marketData.subscribe` and `marketData.unsubscribe` take `{epics}`.
  - `OHLCMarketData.subscribe` takes `{epics, resolutions?, type?}`. Resolutions are
    `MINUTE` (the default), `MINUTE_5`, `MINUTE_15`, `MINUTE_30`, `HOUR`, `HOUR_4`, `DAY`
    and `WEEK`; `type` is `classic` (the default) or `heikin-ashi`.
  - `OHLCMarketData.unsubscribe` takes `{epics, resolutions?, types?}`. A field that is left
    out means all values.
  - `ping`.
- An acknowledgement echoes `destination` and `correlationId` with `status: "OK"`. For
  subscriptions it also carries `payload.subscriptions`, which maps each key to `"PROCESSED"`.
  The key is the epic for quotes and `EPIC:RESOLUTION:type` for OHLC.
- Push events:
  - `quote`: `{epic, product, bid, bidQty, ofr, ofrQty, timestamp(ms)}`.
  - `ohlc.event`: `{resolution, epic, type, priceType: "bid"|…, t(ms), o, h, l, c}`.
- Limits: at most 40 instruments. The session lasts 10 minutes unless the service is pinged
  at least once every 10 minutes. The stream "falls off" when the account is switched with
  `PUT /session`.

## 3. What the demo probe found (2026-11-12)

A throwaway probe settled the open facts before the plan. It ran on a temporary branch, which
was deleted afterwards, and logged no tokens, account ids or deal ids. The connections in it
sent no protocol-level pings, so only the application `ping` was measured.

| # | Question | Observed | Decision |
|---|---|---|---|
| P1 | Does a WS `ping` keep the REST session alive? | Yes. Tokens pinged over WS every 4 min still worked on REST after 13 min with no REST call. Unpinged tokens got `401` | A ping ack calls `SessionManager.mark_used()` |
| P2 | Do subscriptions survive a new login? | Yes. A second login left the stream untouched, and pings with the old or the new tokens both answered `OK` | No reconnect on renewal; every frame carries the current tokens |
| P3 | Which host? | `streamingHost` and `streamEndpoint` on demo are both `wss://api-streaming-capital.backend-capital.com/`, the documented host | One constant for both environments: the documented URL with `/connect` |
| P4 | What do refusals look like? | Per key, inside an `OK` answer: `"ERROR: <epic> not found"`, `"ERROR: Max Subscription limit reached."`, `"ERROR: SECOND not found"`; `"ALREADY_SUBSCRIBED"` also occurs. Whole frame: `status: "ERROR"` with `payload.errorCode` (`error.invalid.session.token`, `error.null.epic`). No refusal closed the socket | §5.4 |
| P5 | How is the 40 limit counted? | For quotes: the 41st epic was refused. OHLC subscriptions were accepted beside 40 quote epics, so the two counts are separate. A 41-epic OHLC call came back with 39 keys, two short | Two counts, 40 each; every requested key must appear in the ack |
| P6 | How often does `ohlc.event` come? | For `MINUTE`, one event per bar and per side (`bid` and `ask`) over two minutes, with the extra field `lastTradedVolume` | `Candle` carries no "closed" flag (the server says nothing about it) and an optional `volume` |
| P7 | What happens after 10 min without a ping, and after `DELETE /session`? | Neither closed the socket: quotes kept arriving for 13 min with no ping and after the REST session expired. After `DELETE /session` quotes slowed, and `ping` answered `error.invalid.session.token` | The keepalive is what detects a dead session, and it gets fresh tokens (§5.3) |

`PUT /session` could not be probed: the demo user has one account. The account-switch row in
§5.3 therefore stays untested on the server, as in stage 2a, and is covered by unit tests.

## 4. Goals, non-goals, anti-goals

Goals:
- Live quotes and OHLC bars for up to 40 instruments, with subscribe and unsubscribe while
  the stream runs.
- Typed events: prices as `Decimal`, times as aware UTC `datetime`, and `.raw` kept, as in REST.
- The stream survives what normally happens in a day of running: network drops, the
  10-minute session, token renewal and an account switch. Every interruption reaches the
  caller as an event.

Non-goals (2.0):
- An async API.
- Callbacks run on a library thread.
- Building bars from quotes, keeping order books or recording to disk.
- Streaming for the legacy `CapitalClient`. 1.0.4 had none.
- More than 40 instruments by opening several connections.

Anti-goals:
- A gap in the data that the caller cannot see.
- Session tokens in logs, `repr()` or exception messages. Frames carry the tokens, so raw
  frames are never logged.
- A background thread that dies and leaves the bot waiting forever.
- TLS verification that can be switched off, or tokens sent to a host the library did not
  choose.

## 5. Design

### 5.1 Public shape

```python
from capitalcom import CapitalCom, Candle, Gap, Quote, Resolution

with CapitalCom(api_key, identifier, password) as cc, cc.stream.connect() as stream:
    stream.subscribe_quotes(["EURUSD", "GOLD"])
    stream.subscribe_ohlc(["EURUSD"], [Resolution.MINUTE_5])   # classic bars by default
    for event in stream:                    # Quote | Candle | Gap
        match event:
            case Quote():  ...
            case Candle(): ...
            case Gap():    ...              # the stream was down from .since to .until
```

- `cc.stream.connect()` returns a `Stream`. It is a context manager and an iterator. One
  `CapitalCom` holds at most one open `Stream`; a second `connect()` raises
  `ValidationError`.
- `subscribe_quotes`, `unsubscribe_quotes`, `subscribe_ohlc(epics, resolutions=(MINUTE,),
  candle=CandleType.CLASSIC)` and `unsubscribe_ohlc(epics, resolutions=None, candles=None)`
  send the message and wait for its acknowledgement, matched by `correlationId`.
  - Events that arrive in the meantime are buffered and delivered in order.
  - A key that comes back as anything other than `PROCESSED` or `ALREADY_SUBSCRIBED`, or that
    is missing from the ack, raises (§5.4).
  - The client checks the limits before anything is sent: at most 40 quote epics and at most
    40 OHLC epics. A call that would exceed either raises `ValidationError`.
- `Quote(epic, bid, bid_size, offer, offer_size, time, raw)` and
  `Candle(epic, resolution, candle_type, price_side, time, open, high, low, close, volume,
  raw)`
  are frozen, slotted dataclasses.
  - `price_side` is `BID` or `ASK`.
  - `time` comes from the server's milliseconds as an aware UTC `datetime`.
  - Prices are parsed with `parse_float=Decimal`. `volume` is `lastTradedVolume`, or `None`
    when it is absent.
- `Gap(since, until, reason)` is yielded once after a reconnect and its resubscription
  succeed. `since` is the time of the last event before the drop. `reason` is one of
  `NETWORK`, `ACCOUNT_SWITCHED` and `SERVER_CLOSED`.
- `Stream.close()` unsubscribes nothing and closes the socket. `CapitalCom.close()` and
  `__exit__` close an open stream before `DELETE /session`.

### 5.2 Threading model: pull, in the caller's thread

The library starts no thread of its own. The caller's `for` loop drives everything:
- `__next__` receives with a timeout set to the time left until the next keepalive is due.
- When it times out, it sends `ping` and waits again.
- Nothing runs between two `__next__` calls.

Why, against a reader thread with callbacks:
- An exception in a callback on a library thread either kills the feed in silence or needs an
  error channel the caller must remember to read. In the pull model every error is raised
  where the caller iterates.
- The REST client is already safe to call from the loop body, because the session manager
  holds a lock. Callbacks would make every user think about thread safety.
- A caller who wants the feed in the background runs the loop in their own thread or queue.
  That is their code, with their error handling.

Costs, to be documented:
- The keepalive interval is 5 minutes, half the server's 10.
- A loop body that blocks for longer than that leaves the REST session unrenewed. The server
  keeps the socket open (P7), so no data is lost; the next keepalive simply gets fresh tokens.
- No library code drops quotes. While the caller is slow, unread frames wait in the
  adapter's bounded receive queue, and when that queue is full the adapter stops reading the
  socket. Staleness is visible from `Quote.time`. (Correction found in review: the library's
  own protocol keepalive would then miss its pongs and drop the link, so it is off; see
  ADR 0012.)

### 5.3 Reconnects, tokens and account switches

- Drops that lead to a reconnect:
  - the socket closes or raises;
  - a keepalive acknowledgement does not arrive within 10 s.
- Reconnect policy:
  - Backoff is 1, 2, 4, 8 and then 16 s, with jitter, through the `Clock` port. A reconnect
    whose resubscription succeeds resets the counter.
  - After 5 consecutive failures the iterator raises `StreamError` (a `TransportError`
    subclass), and the `Stream` is closed.
  - A login refusal raises `AuthenticationError` at once, without retries.
- Tokens:
  - Every outgoing frame takes its tokens from `SessionManager.tokens()` at the moment it is
    sent; the stream keeps no tokens of its own.
  - A renewal needs nothing from the stream (P2).
  - A frame answered with `error.invalid.session.token` makes the stream call
    `SessionManager.invalidate()` on the tokens it sent and resend that frame once with fresh
    ones. A second refusal raises `AuthenticationError`. The socket stays open (P7).
- Account switch: `SessionManager.switch_account` bumps a session generation counter. The
  stream compares the counter before each frame. When it differs, the stream reconnects at
  once with reason `ACCOUNT_SWITCHED`, instead of waiting for the server to drop it.
- Resubscription:
  - It replays the stream's full subscription set: quote epics, plus OHLC triples of epic,
    resolution and candle type.
  - If a key is refused on resubscribe (for example, an epic delisted overnight), the
    iterator raises the subscription error (§5.4) rather than streaming the remaining keys
    as if nothing happened.

### 5.4 Errors

- `StreamError(TransportError)`: the stream gave up reconnecting; `__cause__` holds the last
  failure.
- `SubscriptionError(CapitalComError)`, not an `ApiError`, because a WebSocket answer has no
  HTTP status: the frame's status is `ERROR` (its `errorCode` becomes `error_code`), or a key
  is refused (`"ERROR: …"`) or missing from the ack. It carries a
  mapping from each refused key to the server's text, or to `"MISSING"`.
- `ValidationError`: the 40 limit, an empty or duplicate epic list, a second open stream, or
  a call on a closed `Stream`.
- `ResponseFormatError`: a frame that is not a JSON object, or a known event missing a field.
  A frame with an unknown `destination` is logged at DEBUG, by destination name only, and
  skipped, because Capital.com may add event types.
- `capitalcom[streaming]` not installed: `connect()` raises `ImportError` naming the extra,
  as `encrypted_password=True` does for `[encryption]`.

### 5.5 Architecture

- The stream port goes in `application/ports.py`, since a WebSocket is a process boundary:
  `StreamTransport.connect(url) -> Result[StreamConnection, TransportError]`, and
  `StreamConnection.send(text)`, `.receive(timeout_s) -> Result[str | None, TransportError]`
  and `.close()`.
- `application/streaming.py` holds the logic, testable with a fake transport and a fake
  `Clock`:
  - the subscription set;
  - correlation of acknowledgements;
  - the keepalive schedule;
  - the reconnect state machine;
  - frame parsing.
- `infrastructure/websocket_transport.py` is the adapter.
  - It verifies TLS always. It honours a CA bundle path from the injected `requests.Session`
    (`tls_verify`, as in stage 3) by building an `ssl` context with that `cafile`.
  - It sets no proxy of its own, uses no trace logging and logs no frames.
- `api/stream.py` holds the `cc.stream` namespace and `Stream`.
- `domain/streaming.py` holds `Quote`, `Candle`, `Gap`, `CandleType` and `PriceSide`. The
  existing `Resolution` enum of `/prices` has the same eight values and is reused.
- The host is one constant, `wss://api-streaming-capital.backend-capital.com/connect`, for
  both environments (P3). A server-supplied `streamingHost` or
  `streamEndpoint` is never dialled, so a changed field cannot send the tokens elsewhere. The
  contract test asserts that the pinned host still matches what demo reports, so a drift
  shows up in CI.

### 5.6 Dependency (designer's call, open to override)

The extra is `capitalcom[streaming]`, and it uses `websockets>=15`, not `websocket-client`,
which the main spec suggested.
- `websockets` ships type information, so `mypy --strict` checks the adapter.
- It has a maintained synchronous client with `recv(timeout=...)`, protocol-level keepalive,
  an `ssl=` context and proxy support.
- `websocket-client` would need stubs or `Any` at the boundary.

The core runtime dependency stays `requests` only.

## 6. Testing

- Unit tests use the fake `StreamTransport` with scripted frames and the fake `Clock`, with
  no sleeps. They cover:
  - acknowledgement correlation with interleaved events;
  - every `Gap` reason;
  - backoff and giving up after 5 failures;
  - the generation-counter reconnect;
  - resubscription, and a key refused on it;
  - the 40 limit;
  - unknown destinations;
  - tokens never appearing in log records or `repr`.
- Adapter tests run against a local `websockets` server on localhost over TLS, with a
  throwaway self-signed certificate made by `cryptography` (already a dev dependency). They
  check the CA bundle path and that verification failure is refused.
- The contract test runs on demo with the demo host hard-coded. It:
  - subscribes BTCUSD quotes and `MINUTE` OHLC;
  - receives at least one of each within 60 s;
  - unsubscribes, pings and closes.

  It skips when BTCUSD is closed (about 22:00 UTC) and logs no prices tied to the account.
  The 10-minute behaviour stays in the probe (P1, P7), not in CI.

## 7. Records

- ADR 0012 covers the streaming design and the probe's findings.
- The CHANGELOG gets an Added entry. The migration guide gets nothing, because 1.x had no
  streaming.
- The main spec §9 stage 4 gets a one-line pointer to this addendum.

## 8. Calls made by the designer, open to override

- Pull iterator in the caller's thread, with no callbacks and no library threads (§5.2).
- `websockets` instead of `websocket-client` (§5.6).
- One open stream per `CapitalCom` (§5.1).
- Unsubscribing nothing on `close()`, since the server drops the subscriptions with the
  socket.
- Five reconnect attempts, then `StreamError` (§5.3).
- A 5-minute keepalive (§5.2).
- Raising on a key refused during resubscription, instead of streaming what is left.
- The host pinned per environment, never taken from the server (§5.5).
