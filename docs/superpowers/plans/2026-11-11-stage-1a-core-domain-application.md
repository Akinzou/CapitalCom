# Stage 1a — Core: Domain and Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the I/O-free core: errors, secrets, the deal-confirmation entity, `Result`, ports, retry and rate-limit policy, the dispatcher, the session manager and the deal confirmer.

**Architecture:** `domain/` holds pure values and entities. `application/` holds ports (`HttpTransport`, `Clock`) and the services that use them, and every service returns `Result`. Tests use in-memory fakes and never sleep for real. Stage 1b adds the adapters, the facade and the contract tests; stage 1a and 1b share one branch and one PR.

**Tech Stack:** Python 3.11 stdlib only (`dataclasses`, `decimal`, `threading`, `graphlib`, `email.utils`), plus pytest.

**Spec:** `docs/superpowers/specs/2026-11-11-capitalcom-v2-design.md` (§6.2–6.5). Continued in `2026-11-11-stage-1b-adapters-facade-contract.md`.

## Global Constraints

- Every Stage 0 constraint applies: 300 lines, English, decision comments, no attribution trailers, and grep before delete.
- Branch: `rewrite/stage-1-core`, from `master` after stage 0 merges.
- Layering comes from ADR 0003 and is enforced by `tests/architecture`. Domain and application never import `requests`, `time`, or `socket`.
- Money, price, size and distance are `Decimal`. JSON is decoded with `parse_float=Decimal`. Datetimes are timezone-aware UTC.
- Models are `@dataclass(frozen=True, slots=True)`. The original payload lives in `raw: Mapping[str, Any] = field(repr=False, compare=False)`.
- Every public class and function has a docstring, which mkdocstrings will render in stage 5.
- Every module gets its logger from `capitalcom.application.logs.get_logger(__name__)` (Task 6). The library never calls `basicConfig`. Headers, request bodies, and `Secret` values are never logged.

## Review Focus

1. A secret leaks through an auto-generated `repr` or an error message. The `repr`/`str` of `HttpRequest`, `Credentials`, `SessionTokens` and every error must not contain the API key, password, CST or security token. Pinned by Tasks 1, 3 and 6.
2. Eight threads hit an expired session at the same moment. Exactly one `POST /session` must go out. Pinned by Task 6, `test_concurrent_expiry_logs_in_once`.
3. A proxy returns an HTML 502 or an empty body. The result must be an `ApiError` with `error_code=None`, the body truncated to 500 characters, and no `JSONDecodeError`. Pinned by Task 5.
4. `Retry-After` arrives as `"2"`, as an HTTP-date, or as garbage. The client must wait 2 s, wait until the date (never negative), or fall back to computed backoff. Pinned by Task 4.
5. A POST times out after the request was sent. The client must not retry, and must raise `OutcomeUnknownError`. A GET in the same case is retried. Pinned by Task 5.

---

### Task 1: Errors, `Secret`, enums

**Files:** Create `src/capitalcom/domain/{__init__,errors,secret,enums}.py` and `tests/unit/domain/test_errors_secret_enums.py`.

**Interfaces (Produces):**
- `CapitalComError(Exception)` and its children:
  - `ValidationError` (a local rule violation);
  - `ApiError(status: int, error_code: str | None, body: str)`;
  - `TransportError(reached_server: bool)`;
  - `OutcomeUnknownError(method: str, path: str)`;
  - `DealRejectedError(deal_reference: str, reason: str | None)`;
  - `ConfirmationTimeoutError(deal_reference: str)`.
- `ApiError` has these children:
  - `AuthenticationError`;
  - `NotFoundError`;
  - `RateLimitError(..., retry_after: float | None)`;
  - `ResponseFormatError`, for a malformed success payload.
- Designer's call: server-originated errors subclass `ApiError` so they carry `status` and `error_code`. This is recorded in ADR 0005.
- `Secret(value: str)`: `reveal() -> str`. `repr()` and `str()` return `Secret('***')`. `==` uses `hmac.compare_digest`, and `__hash__ = None`.
- `Direction(StrEnum)`: `BUY`, `SELL`.
- `Environment(Enum)`: `DEMO`, `LIVE`, with `rest_url` set to `https://demo-api-capital.backend-capital.com` and `https://api-capital.backend-capital.com` respectively.

- [ ] **Step 1: Write the failing tests.**
  - Every error is `isinstance(e, Exception)` and `isinstance(e, CapitalComError)`.
  - `str(ApiError(400, "error.x", "b"*900))` contains `error.x` and at most 500 body characters.
  - `"hunter2" not in repr(Secret("hunter2"))` and `not in str(...)`, and `Secret("a") == Secret("a")`.
  - `Environment.DEMO.rest_url` equals the literal above.
- [ ] **Step 2: Run** `pytest tests/unit/domain -v` and expect FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Implement**, keeping error attributes public and read-only.
- [ ] **Step 4: Run** the tests again and expect PASS. Then run `pytest tests/architecture` and expect PASS.
- [ ] **Step 5: Commit.** `feat(domain): add error hierarchy, Secret and enums`

### Task 2: Parsing helpers and `DealConfirmation`

**Files:** Create `src/capitalcom/domain/{parsing,confirmation}.py` and `tests/unit/domain/test_confirmation.py`.

**Interfaces (Produces):**
- `to_decimal(value: object, field: str) -> Decimal`. It accepts `Decimal | int | str` and raises `ResponseFormatError` on anything else, including `bool`.
- `to_utc(value: str, field: str) -> datetime`. It parses ISO-8601 with or without fractional seconds. A naive value is treated as UTC; this is an assumption, pinned by the contract test in 1b.
- `AffectedDeal(deal_id: str, status: str)`.
- `Outcome(Enum)`: `ACCEPTED`, `REJECTED`, `PENDING`.
- `DealConfirmation` has these fields:
  - `deal_reference: str`, `deal_id: str | None`, `deal_status: str | None`, `status: str | None`;
  - `epic: str | None`, `direction: Direction | None`;
  - `level: Decimal | None`, `size: Decimal | None`;
  - `reason: str | None`, `affected_deals: tuple[AffectedDeal, ...]`, `date: datetime | None`;
  - `raw`.
- `DealConfirmation.from_api(payload: Mapping[str, Any]) -> DealConfirmation` raises `ResponseFormatError` when `dealReference` is missing.
- The `reason` field reads `payload.get("reason") or payload.get("rejectReason")`. This is an assumption; the rejection shape is undocumented, and 1b pins it.
- `DealConfirmation.outcome -> Outcome`. The rules:
  - `deal_status` of `"ACCEPTED"` with a `deal_id` gives `ACCEPTED`.
  - `"ACCEPTED"` without a `deal_id` gives `PENDING`. Version 1.0.4 already saw incomplete confirms.
  - `None` gives `PENDING`.
  - `"REJECTED"` gives `REJECTED`.
  - Any other value raises `ResponseFormatError`, naming the value. Nothing is defaulted silently.

- [ ] **Step 1: Write the failing tests.**
  - Parse the documented sample below and assert `outcome is Outcome.ACCEPTED`, `level == Decimal("1.1234")`, and `date.tzinfo is UTC`:

    ```python
    {"date": "2020-09-23T09:43:39.297", "status": "OPEN", "dealStatus": "ACCEPTED", "epic": "EURUSD",
     "dealReference": "o_1", "dealId": "d_1", "affectedDeals": [{"dealId": "d_1", "status": "OPENED"}],
     "level": Decimal("1.1234"), "size": Decimal("1000"), "direction": "BUY",
     "guaranteedStop": False, "trailingStop": False}
    ```

  - Accepted without `dealId` gives `PENDING`.
  - `"REJECTED"` with `reason` gives `REJECTED` and keeps the reason.
  - `"WEIRD"` raises `ResponseFormatError`.
  - A missing `dealReference` raises.
  - `to_decimal(1.5, "x")` raises: a float means the decoder was bypassed.
- [ ] **Step 2: Run** the tests and expect FAIL. **Step 3: Implement.** **Step 4: Run** and expect PASS.
- [ ] **Step 5: Commit.** `feat(domain): add DealConfirmation with explicit outcome`

### Task 3: `Result`, ports, JSON codec

**Files:** Create `src/capitalcom/application/{__init__,result,ports,json_codec}.py`, `tests/fakes.py`, and `tests/unit/application/test_result_ports_codec.py`.

**Interfaces (Produces):**
- `Ok[T](value)` and `Err[E: CapitalComError](error)` are frozen dataclasses. `Result = Union[Ok[T], Err[E]]`.
- `Ok.unwrap() -> T`. `Err.unwrap() -> NoReturn` raises `error`. The facade is the only caller of `unwrap`.
- `HttpRequest(method: str, path: str, headers: Mapping[str, str] = {}, params: Mapping[str, str] = {}, json: Mapping[str, Any] | None = None)`. Its `__repr__` shows only the method and path.
- `HttpResponse(status: int, headers: Mapping[str, str], body: bytes)`:
  - `header(name) -> str | None` is case-insensitive;
  - `json() -> Any` decodes with `decode_json` and raises `ResponseFormatError` on invalid JSON.
- `class HttpTransport(Protocol)`: `send(request: HttpRequest) -> Result[HttpResponse, TransportError]`.
- `class Clock(Protocol)`: `monotonic() -> float`, `now_utc() -> datetime`, `sleep(seconds: float) -> None`.
- `encode_json(body: Mapping[str, Any]) -> bytes`:
  - A `Decimal` is written as a JSON number.
  - A `Decimal` with more than 15 significant digits raises `ValidationError`, because a binary float would round it. This is recorded in ADR 0005.
- `decode_json(body: bytes) -> Any` uses `parse_float=Decimal`.
- `path_segment(value: str) -> str` returns `urllib.parse.quote(value, safe="")`. This blocks path injection through deal ids and epics.
- In `tests/fakes.py`:
  - `FakeClock`: time starts at 0. `sleep` advances time and records each call in `.sleeps: list[float]`.
  - `FakeTransport(script: list[HttpResponse | TransportError])`: thread-safe. It records each `HttpRequest` in `.requests`.

- [ ] **Step 1: Write the failing tests.**
  - `Err(NotFoundError(...)).unwrap()` raises `NotFoundError`.
  - `"hunter2" not in repr(HttpRequest("POST", "/api/v1/session", {"X-CAP-API-KEY": "hunter2"}, json={"password": "hunter2"}))`.
  - `encode_json({"size": Decimal("0.0010")}) == b'{"size": 0.001}'`.
  - `decode_json(b'{"a": 1.10}')["a"] == Decimal("1.10")`.
  - `HttpResponse(502, {}, b"<html>").json()` raises `ResponseFormatError`.
  - `path_segment("a/b") == "a%2Fb"`.
- [ ] **Step 2: Run** the tests and expect FAIL. **Step 3: Implement.** **Step 4: Run** and expect PASS.
- [ ] **Step 5: Commit.** `feat(application): add Result, ports and Decimal-safe JSON codec`

### Task 4: Retry policy and rate limiter

**Files:** Create `src/capitalcom/application/{retry,rate_limiter}.py` and `tests/unit/application/test_retry_rate_limiter.py`.

**Interfaces (Produces):**
- `RetryPolicy(max_attempts: int = 3, base_delay_s: float = 0.5, max_delay_s: float = 8.0)`.
- `backoff_delay(policy, attempt: int, retry_after: float | None, rand: Callable[[], float]) -> float`:
  - If `retry_after` is not `None`, return `min(retry_after, 60.0)`.
  - Otherwise return `min(max_delay, base * 2**attempt) * (0.5 + rand() / 2)`, which is equal jitter.
- `parse_retry_after(value: str | None, now: datetime) -> float | None`:
  - accepts delta-seconds or an HTTP-date (`email.utils.parsedate_to_datetime`);
  - clamps to ≥ 0;
  - returns `None` for garbage and logs it at DEBUG.
- `is_idempotent(method: str) -> bool`: only `GET` returns true.
- `TokenBucket(rate_per_s: float, capacity: int)`: `reserve(now: float) -> float` returns the wait in seconds and consumes the token.
- `RequestKind(Enum)`: `GENERAL`, `TRADE`, `SESSION`.
- `classify(method, path) -> frozenset[RequestKind]`:
  - `POST /api/v1/session` → GENERAL + SESSION;
  - `POST /api/v1/positions` and `POST /api/v1/workingorders` → GENERAL + TRADE;
  - anything else → GENERAL.
- `RateLimiter(clock: Clock, buckets: Mapping[RequestKind, TokenBucket] | None = None)`:
  - `acquire(method, path) -> None` reserves under a `threading.Lock` and sleeps outside it.
  - Default buckets: GENERAL `(10, 10)`, TRADE `(10, 1)`, SESSION `(1, 1)`.

- [ ] **Step 1: Write the failing tests.**
  - `parse_retry_after("2", now) == 2.0`.
  - An HTTP-date 3 s after `now` gives `3.0`. A date in the past gives `0.0`. `"soon"` gives `None`.
  - `backoff_delay(RetryPolicy(), 10, None, lambda: 1.0) == 8.0`.
  - Eleven `acquire("GET", "/api/v1/accounts")` calls on a `FakeClock` give one sleep of about 0.1 s.
  - Two `acquire("POST", "/api/v1/positions")` calls give a second wait of about 0.1 s.
  - Two session acquires give about 1.0 s.
- [ ] **Step 2: Run** the tests and expect FAIL. **Step 3: Implement.** **Step 4: Run** and expect PASS.
- [ ] **Step 5: Commit.** `feat(application): add retry policy and token-bucket rate limiter`

### Task 5: Error mapping and `Dispatcher`

**Files:** Create `src/capitalcom/application/{error_mapping,dispatcher}.py` and `tests/unit/application/test_dispatcher.py`.

**Interfaces:**
- Consumes: Task 3 ports and Task 4 policy.
- Produces `error_for(response: HttpResponse, now: datetime) -> ApiError`:
  - 401 → `AuthenticationError`, 404 → `NotFoundError`, 429 → `RateLimitError` with `retry_after` filled in, any other status → `ApiError`.
  - `error_code` comes from the JSON `errorCode` when the body is a JSON object; otherwise it is `None`.
- Produces `Dispatcher(transport, clock, limiter, policy, rand=random.random)`, with `send(request: HttpRequest) -> Result[HttpResponse, CapitalComError]`:
  - Every attempt calls `limiter.acquire(...)` first.
  - A 2xx returns `Ok`.
  - A 429 is retried after `backoff_delay` until `max_attempts`, then returns `Err(RateLimitError)`.
  - A transport error on `GET`, or a 502/503/504 on `GET`, is retried with backoff.
  - A transport error on a non-`GET` request is never retried:
    - `reached_server=False` gives `Err(TransportError)`;
    - anything else gives `Err(OutcomeUnknownError(method, path))`.
  - Any other status gives `Err(error_for(...))`, with no retry.

- [ ] **Step 1: Write the failing tests.** Script `FakeTransport` for each scenario:
  - 429 (`Retry-After: 2`), then 200: the result is `Ok` and `clock.sleeps` contains `2.0`.
  - Three 429s: `Err(RateLimitError)`.
  - POST with `TransportError(reached_server=True)`: `Err(OutcomeUnknownError)`, and the transport saw exactly one request.
  - GET with a transport error, then 200: `Ok`.
  - 502 with an HTML body of 2000 characters: `ApiError`, `error_code is None`, body length ≤ 500.
  - 401 with `{"errorCode":"error.invalid.api.key"}`: `AuthenticationError` with that code.
- [ ] **Step 2: Run** the tests and expect FAIL. **Step 3: Implement.** **Step 4: Run** and expect PASS.
- [ ] **Step 5: Commit.** `feat(application): add dispatcher with idempotency-aware retries`

### Task 6: `SessionManager` and `ApiClient`

**Files:** Create `src/capitalcom/application/{session,api_client,logs}.py` and `tests/unit/application/test_session_api_client.py`.

**Logging (spec §6.5):**
- `logs.get_logger(name) -> Logger` returns a child of `capitalcom` with the shared `RedactionFilter` attached.
  - We attach the filter to every child because logger filters are not inherited by child loggers.
  - `get_logger` also attaches one `NullHandler` to `capitalcom`.
- `logs.register_secret(value: str) -> None` is called for the API key, the password, and every issued token.
- The filter replaces those values with `***` in `record.msg` and in `record.args`.
- Test: a token logged through `get_logger("capitalcom.x").warning("t=%s", tok)` shows up in `caplog` as `t=***`.

**Interfaces:**
- Consumes: `Dispatcher.send`, `Clock`, `Secret`.
- Produces:
  - `Credentials(api_key: Secret, identifier: str, password: Secret)`.
  - `SessionTokens(cst: Secret, security_token: Secret, generation: int)`, with `headers() -> dict[str, str]`.
  - `SessionManager(dispatcher, clock, credentials)`, with:
    - `tokens() -> Result[SessionTokens, CapitalComError]`. It logs in under a lock when there are no tokens or when `now - last_used >= 600 - 30`.
    - `mark_used() -> None`.
    - `invalidate(stale: SessionTokens) -> None`. It clears only when `stale.generation` is current.
    - `logout() -> Result[None, CapitalComError]`.
  - Login sends `POST /api/v1/session`:
    - header `X-CAP-API-KEY`;
    - body `{"identifier", "password", "encryptedPassword": False}`;
    - it reads the `CST` and `X-SECURITY-TOKEN` response headers; a missing header gives `ResponseFormatError`.
  - `ApiClient(dispatcher, session)`, with `call(method: str, path: str, *, params=None, json=None) -> Result[Any, CapitalComError]`:
    - It adds the token headers and sends the request.
    - On a 401 it invalidates the session, re-authenticates **once**, and resends. The server did not act on the 401.
    - On success it calls `mark_used()` and returns `response.json()`, or `None` for an empty body.

- [ ] **Step 1: Write the failing tests.**
  - Lazy login on the first call.
  - No re-login at t = 569 s; re-login at t = 570 s.
  - A 401 followed by a successful re-login and a 200 gives `Ok`, with exactly two `POST /session` requests.
  - A 401 after re-login gives `Err(AuthenticationError)`, with no loop.
  - A missing `CST` header gives `ResponseFormatError`.
  - `"pw" not in repr(Credentials(...))` and not in `repr(SessionTokens(...))`.
  - `test_concurrent_expiry_logs_in_once`: 8 threads behind a `threading.Barrier` call `tokens()` on an expired session. The `FakeTransport` counts exactly one `POST /api/v1/session`.
- [ ] **Step 2: Run** the tests and expect FAIL. **Step 3: Implement.** **Step 4: Run** and expect PASS.
- [ ] **Step 5: Commit.** `feat(application): add thread-safe session manager and authenticated API client`

### Task 7: `DealConfirmer`

**Files:** Create `src/capitalcom/application/confirmer.py` and `tests/unit/application/test_confirmer.py`.

**Interfaces:**
- Consumes: `ApiClient.call`, `Clock`, `DealConfirmation`.
- Produces `DealConfirmer(api: ApiClient, clock: Clock, timeout_s: float = 5.0, interval_s: float = 0.1)`, with `confirm(deal_reference: str) -> Result[DealConfirmation, CapitalComError]`:
  - It polls `GET /api/v1/confirms/{path_segment(ref)}`.
  - A `NotFoundError` or the `PENDING` outcome means sleep `interval_s` and try again.
  - `ACCEPTED` returns `Ok`.
  - `REJECTED` returns `Err(DealRejectedError(ref, reason))`.
  - Any other error is returned at once.
  - When the deadline passes it returns `Err(ConfirmationTimeoutError(ref))`.

- [ ] **Step 1: Write the failing tests.**
  - 404, 404, then accepted: `Ok`, and `sleeps == [0.1, 0.1]`.
  - Rejected with a reason: `DealRejectedError` with that reason.
  - Always 404: `ConfirmationTimeoutError` after about 5 s of fake time.
  - A 500: an immediate `Err(ApiError)`.
  - The reference `"o_/x"` is requested as `o_%2Fx`.
- [ ] **Step 2: Run** the tests and expect FAIL. **Step 3: Implement.** **Step 4: Run** and expect PASS. Then run the full suite: `ruff check . && mypy && pytest`.
- [ ] **Step 5: Commit.** `feat(application): add deal confirmer`
