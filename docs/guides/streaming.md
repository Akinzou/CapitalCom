# Streaming

Capital.com pushes quotes and OHLC bars over a WebSocket. Streaming needs the `streaming`
extra, installed with `pip install "capitalcom[streaming]"`. Without it,
`cc.stream.connect()` raises `ImportError` naming the extra. REST-only code never
imports the WebSocket library.

## A first stream

```python
--8<-- "docs/examples/streaming.py:stream"
```

`cc.stream.connect()` logs in if needed, opens the socket and returns a `Stream`. Use it as a
context manager, or call `stream.close()`; `cc.close()` also closes it. One `CapitalCom` holds
at most one open stream: a second `connect()` while one is open raises `ValidationError`.

The stream dials one pinned host, the same for demo and live. The streaming endpoint the
session reports is never used, so a changed or injected value cannot send your session tokens
to another host ([ADR 0012](../adr/0012-streaming.md)).

## Subscriptions

- `stream.subscribe_quotes(epics)` and `stream.unsubscribe_quotes(epics)`.
- `stream.subscribe_ohlc(epics, resolutions, candle)`, by default one-minute classic bars.
  Each epic is subscribed in each resolution given.
- `stream.unsubscribe_ohlc(epics, resolutions, candles)`, where `None` means every
  resolution or every candle type.

`epics` is a list. A bare string, an empty list or a repeated epic raises `ValidationError`,
and so does unsubscribing something that is not subscribed. An epic already subscribed is not
sent again.

Each subscribe call waits for the server's answer. A refused key raises `SubscriptionError`:
its `refused` maps each refused key to the server's text, or to `"MISSING"` when the answer
left a requested key out. Refused keys are not kept
([ADR 0012](../adr/0012-streaming.md)).

## Limits

At most 40 epics for quotes and 40 for OHLC bars per stream, counted separately. An OHLC epic
counts once, whatever its number of resolutions. The limits are checked before anything is
sent: a call that would exceed one raises `ValidationError` and changes nothing
([ADR 0012](../adr/0012-streaming.md)).

## Events

Iterating a stream yields three kinds of event:

- `Quote`: `epic`, `bid`, `bid_size`, `offer`, `offer_size` and the server `time` in UTC.
- `Candle`: one bar of one side of the book (`price_side` is bid or ask; the server sends a
  bar per side), with `epic`, `resolution`, `candle_type`, `open`, `high`, `low`, `close`,
  an optional `volume`, and `time`, the bar's UTC start. The server does not say when a bar is
  final, so the same bar may arrive again with new values.
- `Gap`: the stream delivered nothing between `since` and `until`, and events may be missing;
  `reason` says why.

Prices are `Decimal`.

## Threading model

The library starts no thread. Iteration blocks in your thread, and the keepalive, the
resubscriptions and the reconnects all run inside `next()`. Every error is raised where you
iterate. For a background feed, run the loop in a thread of your own
([ADR 0012](../adr/0012-streaming.md)).

- Use a stream from one thread. A call from a second thread while another is in progress
  raises `ValidationError`, because one socket cannot be read by two threads.
- `stream.close()` may come from any thread, to stop a loop running in another. That loop
  then ends instead of reconnecting.

## Keepalive

Every 5 minutes the stream sends a ping and waits 10 seconds for its answer. The ping also
keeps the REST session alive. A loop body that blocks for longer than 5 minutes delays the
ping; the server keeps the socket open, and the next ping uses fresh tokens. A half-open
connection is noticed within about 5 minutes and 10 seconds and reported as a `Gap`
([ADR 0012](../adr/0012-streaming.md)).

## Reconnects and gaps

The stream reconnects when:

- the socket drops;
- an answer to a subscription or keepalive is missing for 10 seconds;
- the session has moved to another account.

Before each of up to five attempts it waits 1, 2, 4, 8 and then 16 seconds, half of each
wait random, and it resubscribes everything on the new connection. Events read before the drop come out first,
then one `Gap`, then events from the new connection
([ADR 0012](../adr/0012-streaming.md)).

The `Gap` reason is:

- `ACCOUNT_SWITCHED` when the session moved to another account, even when the switch came
  from another thread;
- `SERVER_CLOSED` when the server started the close;
- `NETWORK` otherwise, including a close our side started.

`since` is the time of the last event delivered or read before the drop, and a gap never
starts before the previous one ended. Treat every `Gap` as missed prices: resynchronise what
depends on them, for example with `cc.prices.history`.

## When the stream gives up

After five failed reconnect attempts the stream raises `StreamError`, a `TransportError`
whose `__cause__` is the last failure. A refused login or a refused key on resubscription is
raised at once instead. A frame refused for an invalid session is sent once more with fresh
tokens; a second refusal raises `AuthenticationError` and closes the stream
([ADR 0012](../adr/0012-streaming.md)).

Giving up closes the socket but keeps what was already read:

- inside the loop, the buffered events come first, then `next()` raises the error, then
  iteration ends;
- when a subscribe call gave up, that call raises, and iteration then yields the buffered
  events without raising again;
- only an explicit `close()` drops unread events.

After a give-up `stream.closed` is `True`, and `cc.stream.connect()` opens a new stream; the
subscriptions are not carried over.

A frame that cannot be decoded raises `ResponseFormatError` from `next()` at its position
among the events. The stream stays open, also when the frame came during a reconnect: catch
the error and keep reading, and a new `for` loop over the same stream goes on with the next
event (`tests/unit/api/test_stream_errors.py`,
`tests/unit/application/test_stream_malformed.py`). Frames of kinds the library does not know
are skipped ([ADR 0012](../adr/0012-streaming.md)).
