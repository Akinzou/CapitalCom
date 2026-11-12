# Stage 4 — WebSocket Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cc.stream.connect()` delivers typed quotes and OHLC bars from the Capital.com WebSocket and reports every interruption as a `Gap`.

**Architecture:**
- Pure rules (events, subscription set, limits) live in `domain`.
- The protocol logic (frames, acknowledgements, keepalive, reconnects) lives in `application` behind a new `StreamTransport` port, so the whole state machine runs against a scripted fake and `FakeClock`.
- The `websockets` adapter in `infrastructure` is the only module that touches a socket.
- `api/stream.py` turns `Result`s into exceptions, as the REST resources do.

**Tech Stack:** Python ≥3.11, `websockets>=15` (sync client) as the `streaming` extra, pytest, `cryptography` (dev, for test certificates).

**Spec:** `docs/superpowers/specs/2026-11-12-streaming-addendum.md`, which extends `docs/superpowers/specs/2026-11-11-capitalcom-v2-design.md`. The probe facts are in §3 of the addendum.

## Global Constraints

- Every hand-written file stays at or under 300 lines (`tests/architecture/test_file_length.py`).
- `domain` and `application` import no I/O module (`tests/architecture/importgraph.py` allowlist). `websockets` and `ssl` are imported only in `infrastructure/websocket_transport.py`.
- Runtime dependency stays `requests` only. Add `streaming = ["websockets>=15"]` to `[project.optional-dependencies]` and `"websockets>=15"` to the `dev` group.
- Numbers are `Decimal` (frames decoded with `parse_float=Decimal`), times are aware UTC `datetime`, and models are frozen, slotted dataclasses with `.raw`.
- Tokens never reach a log record, `repr()` or an exception message. No frame is logged.
- TLS is always verified. A CA bundle path from an injected `requests.Session` is honoured through `tls_verify`.
- The host is the constant `STREAM_URL = "wss://api-streaming-capital.backend-capital.com/connect"` for both environments. No server-supplied URL is dialled.
- Constants: `KEEPALIVE_S = 300.0`, `ACK_TIMEOUT_S = 10.0`, `MAX_RECONNECTS = 5`, `MAX_QUOTE_EPICS = 40`, `MAX_OHLC_EPICS = 40`. Reconnect backoff reuses `backoff_delay(RetryPolicy(max_attempts=5, base_delay_s=1.0, max_delay_s=16.0), attempt, None, rand)`.
- Tooling gates: ruff, `mypy --strict`, pytest with coverage `fail_under = 95`, and Semgrep (`--severity ERROR`) all green.
- Commits go out with no Claude attribution.

## Rulings taken while planning (for the owner to accept)

1. **Account switch detection.** The stream compares `SessionManager.current_account_id()` with the value it recorded at connect, instead of using a new generation counter. The manager already tracks the account, so no new state is added.
2. **A subscribe whose ack times out** is treated as a dropped connection. The keys stay in the intended set, the stream reconnects and resubscribes everything, and the call returns once those acks pass. A `Gap(NETWORK)` is queued.
3. **Refused keys** are removed from the set before `SubscriptionError` is raised, so the set always matches the server. On resubscribe, a refusal closes the `Stream` and raises.
4. **`AuthenticationError` from a WS frame** uses status `401`, the meaning REST gives the same error, and `error_code="error.invalid.session.token"`.
5. **`GapReason.SERVER_CLOSED` vs `NETWORK`** comes from `TransportError.reached_server`. The adapter sets it to `True` when a close frame was received.
6. **`__next__` on a closed `Stream`** raises `StopIteration`. Every other method raises `ValidationError("stream is closed")`.
7. **Quotes for an epic that is no longer subscribed** (frames still in flight) are delivered. They are real prices, and dropping them would be a hidden filter.
8. **The `websockets` library logger** is replaced by `get_logger("capitalcom.websocket")`, so its DEBUG frame dumps pass through the token-masking filter.

## Review Focus

1. A user enabling DEBUG for all loggers must not see a session token. The test is in Task 5.
2. Events received before a drop come out before the `Gap`, and events received during resubscription after it. The test is in Task 4.
3. A loop body that blocks longer than `KEEPALIVE_S` gets a ping sent before the next receive, not after it. The test is in Task 3.
4. Subscribing to an epic already subscribed sends nothing and does not count twice toward the limit. The test is in Task 1.
5. `CapitalCom.close()` with an open stream closes the socket before `DELETE /session`, even when the socket close fails. The test is in Task 6.

---

### Task 1: Domain values, parsing, subscription set and errors

**Files:**
- Create: `src/capitalcom/domain/streaming.py`, `src/capitalcom/domain/subscriptions.py`
- Modify: `src/capitalcom/domain/errors.py`, `src/capitalcom/domain/enums.py`
- Test: `tests/unit/domain/test_streaming.py`, `tests/unit/domain/test_subscriptions.py`

**Interfaces:**
- Produces, in `streaming.py`:
  - `CandleType(StrEnum)`: `CLASSIC="classic"`, `HEIKIN_ASHI="heikin-ashi"`.
  - `PriceSide(StrEnum)`: `BID="bid"`, `ASK="ask"`.
  - `GapReason(StrEnum)`: `NETWORK`, `SERVER_CLOSED`, `ACCOUNT_SWITCHED`.
  - `Quote(epic, bid, bid_size, offer, offer_size, time, raw)`, `Candle(epic, resolution: Resolution, candle_type, price_side, time, open, high, low, close, volume: int | None, raw)` and `Gap(since: datetime, until: datetime, reason: GapReason)`.
  - `parse_quote(payload: Mapping[str, Any]) -> Quote` and `parse_candle(payload: Mapping[str, Any]) -> Candle`. Both raise `ResponseFormatError` through the `parsing.py` helpers.
- Produces, in `subscriptions.py`: `OhlcKey(epic, resolution, candle_type)` with `wire() -> str` (`"EPIC:RESOLUTION:type"`), and `Subscriptions` with:
  - `add_quotes(epics) -> tuple[str, ...]` and `add_ohlc(epics, resolutions, candle_type) -> tuple[OhlcKey, ...]`, which return only the new keys;
  - `remove_quotes(epics) -> tuple[str, ...]` and `remove_ohlc(epics, resolutions | None, candle_types | None) -> tuple[OhlcKey, ...]`, which return the keys actually removed;
  - `discard(keys)` and the read-only `quotes`, `ohlc`.
  The limits and input checks raise `ValidationError`.
- Produces, in `enums.py`: `STREAM_URL` and `Environment.stream_url`, the same constant for DEMO and LIVE (P3).
- Produces, in `errors.py`:
  - `StreamError(TransportError)`;
  - `SubscriptionError(CapitalComError)`, with `__init__(self, refused: Mapping[str, str], error_code: str | None)` and properties `refused` and `error_code`. The message lists the keys and the server's texts, which carry no tokens.

- [ ] **Step 1: Write the failing tests**:
  - `test_parse_quote_probe_sample`, using the probe frame payload `{"epic":"BTCUSD","product":"CFD","bid":Decimal("73578.2"),"bidQty":Decimal("0.2"),"ofr":Decimal("73628.2"),"ofrQty":Decimal("0.2"),"timestamp":1794446435768}`. It asserts `bid == Decimal("73578.2")`, `offer_size == Decimal("0.2")` and `time == datetime(2026, 11, 12, 1, 20, 35, 768000, tzinfo=UTC)`.
  - `test_parse_candle_probe_sample`, with `lastTradedVolume` 216 giving `volume == 216`, and `test_parse_candle_without_volume`, where `volume is None`.
  - `test_parse_candle_unknown_price_type_raises`.
  - `test_add_quotes_returns_only_new_keys`, which also covers Review Focus 4.
  - `test_41st_quote_epic_raises_and_changes_nothing`.
  - `test_ohlc_limit_counts_epics_not_keys`: 40 epics × 2 resolutions are allowed, and the 41st epic raises.
  - `test_quote_and_ohlc_limits_are_separate`.
  - `test_empty_duplicate_or_blank_epics_raise`.
  - `test_remove_ohlc_none_means_all_resolutions_and_types`.
  - `test_remove_unsubscribed_epic_raises`.
  - `test_subscription_error_carries_refused_keys`.
  - `test_stream_url_is_pinned_for_both_environments`.
- [ ] **Step 2: Run** `pytest tests/unit/domain/test_streaming.py tests/unit/domain/test_subscriptions.py -v`. Expected: FAIL with `ModuleNotFoundError: capitalcom.domain.streaming`.
- [ ] **Step 3: Implement** the interfaces above. Reuse the existing `Resolution` enum and `parsing.py` helpers (`epoch_ms_to_utc`, `require_decimal`).
- [ ] **Step 4: Run** the same tests. Expected: PASS. Then run the full suite.
- [ ] **Step 5: Commit** `feat(stream): add streaming events, the subscription set and stream errors`.

### Task 2: Frames and acknowledgements

**Files:**
- Create: `src/capitalcom/application/stream_frames.py`
- Test: `tests/unit/application/test_stream_frames.py`

**Interfaces:**
- Consumes: `SessionTokens`, `decode_json`, and everything from Task 1.
- Produces:
  - `encode_frame(destination: str, correlation_id: str, tokens: SessionTokens, payload: Mapping[str, Any] | None) -> str`;
  - `Incoming = Ack | Event | Unknown`, where `Ack(correlation_id, status, payload, error_code)`, `Event(value: Quote | Candle)` and `Unknown(destination: str)`;
  - `decode_frame(text: str) -> Incoming`, which raises `ResponseFormatError` for non-JSON, non-object or event-missing-field frames;
  - `check_ack(ack: Ack, expected: Sequence[str]) -> Result[None, SubscriptionError]`. It accepts `PROCESSED` and `ALREADY_SUBSCRIBED`. Any `"ERROR…"` value, any missing key, or `status == "ERROR"` gives `Err`;
  - `is_invalid_session(ack: Ack) -> bool`, true for `error.invalid.session.token`.
- Destinations: `marketData.subscribe`, `marketData.unsubscribe`, `OHLCMarketData.subscribe` (payload `{epics, resolutions, type}`), `OHLCMarketData.unsubscribe` (payload `{epics, resolutions?, types?}`) and `ping` (no payload).

- [ ] **Step 1: Write the failing tests.** Use the probe frames verbatim from addendum §3:
  - `test_encode_ping_has_no_payload`;
  - `test_frame_repr_and_errors_never_contain_tokens`;
  - `test_decode_quote_event`;
  - `test_decode_ack_with_correlation`;
  - `test_unknown_destination_is_unknown`;
  - `test_non_object_frame_raises_response_format_error`;
  - `test_check_ack_accepts_already_subscribed`;
  - `test_check_ack_reports_error_text_per_key` (`"ERROR: Max Subscription limit reached."`);
  - `test_check_ack_reports_missing_keys_as_MISSING` (the 41-epic ack that came back with 39 keys);
  - `test_check_ack_status_error_carries_error_code` (`error.null.epic`);
  - `test_is_invalid_session`.
- [ ] **Step 2: Run** `pytest tests/unit/application/test_stream_frames.py -v`. Expected: FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Implement.** `decode_frame` uses `decode_json`, whose `parse_float=Decimal` keeps prices exact.
- [ ] **Step 4: Run** the tests. Expected: PASS. Then run the full suite.
- [ ] **Step 5: Commit** `feat(stream): encode and decode stream frames and check acknowledgements`.

### Task 3: Port, fake, and one connection (`StreamLink`)

**Files:**
- Modify: `src/capitalcom/application/ports.py`, `tests/fakes.py`
- Create: `src/capitalcom/application/stream_link.py`
- Test: `tests/unit/application/test_stream_link.py`

**Interfaces:**
- Produces, in `ports.py`:
  - `StreamConnection(Protocol)`: `send(text: str) -> Result[None, TransportError]`, `receive(timeout_s: float) -> Result[str | None, TransportError]` (where `None` means the timeout ran out) and `close() -> None`;
  - `StreamTransport(Protocol)`: `connect(url: str) -> Result[StreamConnection, TransportError]`.
- Produces, in `tests/fakes.py`: `FakeStreamTransport(connections: Sequence[FakeConnection | TransportError])`. A `FakeConnection(script)` holds `str` frames, `TransportError`s, or `Silence(seconds)`. `Silence` advances the shared `FakeClock` and returns `Ok(None)`. The fake records `sent: list[dict]` and answers acks through a responder callable `(sent_frame) -> list[str]`.
- Produces, in `stream_link.py`: `StreamLink(connection, session: SessionManager, clock: Clock)`, with:
  - `request(destination, payload, expected_keys) -> Result[Ack, CapitalComError]`. It sends with `session.tokens()` and waits up to `ACK_TIMEOUT_S`, buffering events. On `is_invalid_session` it calls `session.invalidate(tokens)` and resends once; a second refusal gives `Err(AuthenticationError(401, "error.invalid.session.token", ""))`. An ack timeout gives `Err(TransportError("no acknowledgement", reached_server=True))`;
  - `next_incoming() -> Result[Event | None, CapitalComError]`. It drains the buffer first. It sends `ping` when `KEEPALIVE_S` has passed since the last ping ack, before receiving (Review Focus 3). A ping ack calls `session.mark_used()`. It receives with `timeout = time until the next ping`;
  - `close()`.
  Correlation ids are `"1"`, `"2"`, … per link.

- [ ] **Step 1: Write the failing tests:**
  - `test_request_buffers_events_until_its_ack`;
  - `test_ack_timeout_is_transport_error`;
  - `test_invalid_session_invalidates_and_resends_once`;
  - `test_second_invalid_session_is_authentication_error`;
  - `test_ping_sent_after_keepalive_interval_and_marks_session_used`;
  - `test_overdue_ping_is_sent_before_next_receive`: advance the clock by 400 s between calls, and the first sent frame after that is `ping`;
  - `test_frames_carry_current_tokens_after_renewal` (P2).
- [ ] **Step 2: Run** `pytest tests/unit/application/test_stream_link.py -v`. Expected: FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Implement.** The buffer is a `collections.deque` of `Event`. Unknown destinations are logged at DEBUG by name and skipped.
- [ ] **Step 4: Run** the tests. Expected: PASS. Then run the full suite.
- [ ] **Step 5: Commit** `feat(stream): add the stream port and one acknowledged, kept-alive connection`.

### Task 4: Stream session — subscriptions, reconnects, gaps and account switches

**Files:**
- Create: `src/capitalcom/application/stream_session.py`
- Test: `tests/unit/application/test_stream_session.py`

**Interfaces:**
- Consumes: Tasks 1–3, plus `backoff_delay` and `RetryPolicy`.
- Produces: `StreamSession(transport: StreamTransport, session: SessionManager, clock: Clock, url: str, rand: Callable[[], float] = random.random)`, with:
  - `open() -> Result[None, CapitalComError]`;
  - `subscribe_quotes(epics) -> Result[None, CapitalComError]`, `unsubscribe_quotes(epics)`, `subscribe_ohlc(epics, resolutions, candle_type)` and `unsubscribe_ohlc(epics, resolutions, candle_types)`, all with the same result type;
  - `next_event() -> Result[Quote | Candle | Gap, CapitalComError]` and `close() -> None`.
- Behaviour:
  - Reconnect triggers: a `TransportError` from the link, a ping ack timeout, or `current_account_id()` differing from the value recorded at `open()`.
  - Before each attempt the session sleeps `backoff_delay(...)`. After `MAX_RECONNECTS` failures it gives `Err(StreamError(...))` with `__cause__` set to the last error, and the session closes.
  - `AuthenticationError` and `SubscriptionError` are not retried.
  - After a successful resubscription it queues one `Gap(since=time of last event or of open(), until=clock.now_utc(), reason)`. The `Gap` goes after the events buffered before the drop (Review Focus 2).

- [ ] **Step 1: Write the failing tests:**
  - `test_subscribe_sends_only_new_keys_and_refused_keys_leave_the_set`;
  - `test_drop_reconnects_resubscribes_and_yields_gap`;
  - `test_events_before_drop_precede_gap`;
  - `test_server_close_gives_server_closed_reason`;
  - `test_backoff_sleeps_follow_policy` (rand = 0 → 0.5, 1, 2, 4, 8 s);
  - `test_five_failures_raise_stream_error_with_cause`;
  - `test_auth_error_on_reconnect_is_not_retried`;
  - `test_refusal_on_resubscribe_closes_and_raises`;
  - `test_account_switch_reconnects_with_account_switched_reason`;
  - `test_subscribe_ack_timeout_reconnects_and_keeps_intent` (ruling 2).
- [ ] **Step 2: Run** `pytest tests/unit/application/test_stream_session.py -v`. Expected: FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Implement.** Resubscription sends one `marketData.subscribe` for all quote epics, and one `OHLCMarketData.subscribe` per `(resolutions, candle_type)` group.
- [ ] **Step 4: Run** the tests. Expected: PASS. Then run the full suite.
- [ ] **Step 5: Commit** `feat(stream): reconnect with backoff, resubscribe and report gaps`.

### Task 5: `websockets` adapter

**Files:**
- Create: `src/capitalcom/infrastructure/websocket_transport.py`
- Modify: `pyproject.toml` (extra and dev group)
- Test: `tests/unit/infrastructure/test_websocket_transport.py`

**Interfaces:**
- Produces: `WebsocketTransport(verify: bool | str = True)`, which implements `StreamTransport`. Its `connect(url)`:
  - refuses any scheme other than `wss` with `ValidationError`;
  - builds `ssl.create_default_context(cafile=verify if isinstance(verify, str) else None)`;
  - calls `websockets.sync.client.connect(url, ssl=context, open_timeout=10, logger=get_logger("capitalcom.websocket"))`. The library's default protocol keepalive stays on.
- Its connection maps errors to `Err(TransportError)`:
  - `TimeoutError` from `recv(timeout=...)` gives `Ok(None)`;
  - `ConnectionClosed` gives `reached_server=True` when `exc.rcvd` is not `None`, else `False`;
  - `OSError` and `InvalidHandshake` give `reached_server=False`.

- [ ] **Step 0:** In the installed `websockets` version, confirm the sync client's names: `connect` parameters, `recv(timeout=)`, `ConnectionClosed.rcvd` and `websockets.sync.server.serve`. Any difference from this plan is a ledgered ruling.
- [ ] **Step 1: Write the failing tests.** They use a local `websockets.sync.server.serve` over TLS on `localhost:0` in a thread, with a self-signed certificate made by `cryptography` in a fixture:
  - `test_round_trip_with_ca_bundle_path`;
  - `test_unknown_certificate_is_refused`;
  - `test_receive_timeout_is_ok_none`;
  - `test_server_close_reached_server_true`;
  - `test_ws_scheme_refused`;
  - `test_debug_logging_never_shows_tokens` (Review Focus 1): a session token registered with `register_secret` is sent as a frame with root DEBUG on, and `caplog.text` lacks it.
- [ ] **Step 2: Run** `pytest tests/unit/infrastructure/test_websocket_transport.py -v`. Expected: FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Implement** the adapter, then install the dev group with `pip install -e . --group dev`.
- [ ] **Step 4: Run** the tests. Expected: PASS. Then run the full suite, mypy and Semgrep.
- [ ] **Step 5: Commit** `feat(stream): add the websockets transport with verified TLS`.

### Task 6: Public API, wiring and lifecycle

**Files:**
- Create: `src/capitalcom/api/stream.py`
- Modify: `src/capitalcom/api/composition.py`, `src/capitalcom/api/client.py` and `src/capitalcom/__init__.py`
- Test: `tests/unit/api/test_stream.py` and `tests/unit/api/test_facade.py`

**Interfaces:**
- Produces, in `composition.py`: `stream_transport(http_session: requests.Session | None) -> StreamTransport`. It imports the adapter lazily. A missing `websockets` raises `ImportError("streaming needs the 'streaming' extra: pip install 'capitalcom[streaming]'")`.
- Produces, in `stream.py`:
  - `StreamResource(core, transport_factory)`. Its `connect() -> Stream` opens immediately. A second `connect()` while one is open raises `ValidationError`.
  - `Stream`, with `subscribe_quotes(epics: Sequence[str])`, `unsubscribe_quotes(epics)`, `subscribe_ohlc(epics, resolutions=(Resolution.MINUTE,), candle=CandleType.CLASSIC)`, `unsubscribe_ohlc(epics, resolutions=None, candles=None)`, `close()`, `__enter__`/`__exit__`, `__iter__` and `__next__` (ruling 6). Every `Err` is raised via `unwrap()`.
- `CapitalCom.__init__` adds `self.stream`. `close()` closes an open stream first, in its own `try`, then runs the session logout (Review Focus 5).
- Exports: `Stream`, `Quote`, `Candle`, `Gap`, `GapReason`, `CandleType`, `PriceSide`, `StreamError` and `SubscriptionError`.

- [ ] **Step 1: Write the failing tests:**
  - `test_iteration_yields_quotes_candles_and_gaps`;
  - `test_errors_are_raised_not_returned`;
  - `test_second_connect_raises`;
  - `test_methods_on_closed_stream_raise_and_next_stops`;
  - `test_missing_extra_names_it`: monkeypatch `sys.modules["websockets"] = None`;
  - `test_close_closes_stream_before_logout_even_if_socket_close_fails`;
  - `test_public_exports`.
- [ ] **Step 2: Run** `pytest tests/unit/api/test_stream.py tests/unit/api/test_facade.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Pass `tls_verify(http_session)` when a session is injected, else `True`.
- [ ] **Step 4: Run** the tests. Expected: PASS. Then run the full suite and the architecture tests.
- [ ] **Step 5: Commit** `feat(stream): expose cc.stream and close it before logout`.

### Task 7: Contract test, ADR 0012 and CHANGELOG

**Files:**
- Create: `tests/contract/test_stream_contract.py` and `docs/adr/0012-streaming.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write the contract test** `test_stream_round_trip`, marked `contract`. It uses the `demo_credentials` fixture and `CapitalCom(..., environment=Environment.DEMO)`, and it:
  - asserts `cc.session.info().stream_endpoint.rstrip("/") + "/connect" == Environment.DEMO.stream_url`;
  - subscribes BTCUSD quotes and `MINUTE` OHLC;
  - receives at least one `Quote` and one `Candle` within 90 s;
  - unsubscribes both and closes.
  It skips when BTCUSD's `marketStatus` is not `TRADEABLE`. It logs only event types and counts.
- [ ] **Step 2: Run it locally**, without secrets. Expected: SKIPPED.
- [ ] **Step 3: Write ADR 0012.** It records the pull model, the host pin, the probe table (addendum §3), the error mapping, reconnect and gaps, and the `websockets` choice. Add a CHANGELOG `Added` entry for `cc.stream` and the `streaming` extra.
- [ ] **Step 4: Run** the full suite, ruff, mypy and Semgrep. Expected: all green.
- [ ] **Step 5: Commit** `docs: record the streaming design (ADR 0012) and add the stream contract test`.
