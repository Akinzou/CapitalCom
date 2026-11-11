# Stage 2a — Session Extras, Accounts, History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the rest of the session API (RSA login, account switch, `GET /session`, `/time`), plus `cc.accounts` and `cc.history`, on top of the stage 1 core.

**Architecture:**
- Read models are frozen, slotted dataclasses in `domain/`, built by `from_api` classmethods that use strict converters from `domain/parsing.py`.
- Resources in `api/` take the `Core`, call the application services, and `.unwrap()`. That is the only place where a `Result` becomes an exception.
- Session state (the selected account, encrypted login) stays inside `SessionManager`, because it must hold across automatic re-logins.

**Tech Stack:** Python ≥3.11, `requests`, and `cryptography` through the `encryption` extra only. Tests use pytest, `responses`, and the fakes in `tests/fakes.py`.

**Spec:** `docs/superpowers/specs/2026-11-11-capitalcom-v2-design.md` (§2.1, §5, §6.1, §6.3, §6.5, §9 stage 2). Facts: `docs/adr/0007-partial-close-and-confirmation-facts.md`.

## Stage 2 roadmap (one branch `rewrite/stage-2-rest`, one PR, three plans)

Each plan is written after the previous one is executed, because each consumes the previous plan's real interfaces and contract-probe results.

- **2a (this plan):** session extras, accounts, history, shared parsing helpers.
- **2b:** markets (navigation, search, `get_many`, `get` → `MarketDetails` with `Instrument`, `DealingRules`, snapshot), prices (`Resolution`, `PriceBar`), sentiment, and watchlists.
  - Before writing it, re-fetch the sentiment and watchlist sections of https://open-api.capital.com/ verbatim.
  - Probe `GET /markets/{epic}` for an FX epic: is `pipPosition` present? It is documented only on `GET /markets`.
  - Decide what `DealingRules` does with `PERCENTAGE` and unknown units.
- **2c:** positions and working orders.
  - Request value objects with the documented stop and profit rules, a `DealSubmitter` (submit, then confirm), and opt-in pre-trade validation against 2b's `MarketDetails`.
  - **Ruling (position id, ADR 0007 over spec §6.1):** `positions.open` returns `DealConfirmation`. It gains the property `position_id: str | None`, which is the first `affected_deals` entry whose status is `OPENED`. It is `None` when netting fully closed an opposite position instead.
  - Probes, early in 2c, each with if/else branches: what amend, order create, amend and cancel confirmations look like; whether `PUT /positions/{id}` keeps protections it does not mention; and whether the order id is `affectedDeals[0]`.

## Global Constraints

- All stage 0 and 1 constraints still apply:
  - The runtime dependency is `requests` only. `cryptography` is imported only in `infrastructure/`, and only when encrypted login is requested.
  - Every tracked hand-written file has ≤300 lines.
  - Imports go inward only, and ranks 0–1 (domain, application) use the stdlib allowlist.
  - Commits are made as the owner with no Claude attribution.
- Money, prices, sizes and amounts are `Decimal`. Leverages are `int`.
- Every read model keeps the original payload as `raw: Mapping[str, Any]` (`repr=False`, `compare=False`).
- Timestamps:
  - Only the UTC fields are parsed into `datetime`: `dateUTC`, `dateUtc` (transactions), and epoch milliseconds. Local-time fields stay in `raw`.
  - Query datetimes must be timezone-aware. They are sent as UTC in the form `YYYY-MM-DDTHH:MM:SS`. A naive datetime raises `ValidationError` and sends nothing.
- Read models keep server enumerations (status, type, source, accountType) as `str`, so a new value never breaks a listing. Caller inputs use enums only when the documented set is closed.
- Contract tests:
  - They target demo only (the host is fixed in `tests/contract/conftest.py`) and share the session-scoped `demo_core`.
  - Any state a test changes is restored in `finally`.
  - No contract test calls top-up: the account allows 100 a day and caps the balance at 100000.
- Commands use the repo venv. `pytest` below means `.venv/Scripts/python.exe -m pytest`, and the same applies to `ruff` and `mypy`.

## Review Focus

1. **Re-login after an account switch.** The bot switches to account B, then idles for over 570 s or gets a 401. A fresh `POST /session` lands on the default account A. The next request must still run on B: the manager re-applies the switch inside the login lock, or the call fails. It must never trade on A. Pinned in Task 2.
2. **Switch retried after a lost response.** `PUT /session` counts as retry-safe, so a retry can reach a session that already switched and get a 400. That 400 must count as success, not as an error that hides a completed switch. Pinned in Task 2, and its error code is pinned by the probe in Task 7.
3. **Encrypted login without the extra.** `CapitalCom(..., encrypted_password=True)` without `cryptography` must fail in the constructor with a hint to install `capitalcom[encryption]`. It must not fail at the first trade. Pinned in Task 3.
4. **A naive or reversed time range.** `history.activity(start=naive)`, `start > end`, a span over 1 day, or `last_period` combined with dates must raise `ValidationError` before any request. Pinned in Tasks 1 and 6.
5. **`server_time()` on a fresh client.** It must not log in, because `GET /time` needs no auth. `top_up` on `Environment.LIVE` raises `ValidationError` and sends nothing. Pinned in Tasks 4 and 5.

---

### Task 1: Shared parsing and query-time helpers

**Files:**
- Modify `src/capitalcom/domain/parsing.py` and `src/capitalcom/domain/confirmation.py`, which moves its private helpers to the shared module.
- Create `src/capitalcom/domain/api_time.py`.
- Test: `tests/unit/domain/test_parsing.py`.

**Interfaces (Produces).** Each helper raises `format_error(field, …)` on a wrong type or a missing required value.
- `require_str(payload: Mapping[str, Any], key: str) -> str` and `optional_str(...) -> str | None`.
- `require_decimal(...) -> Decimal` and `optional_decimal(...) -> Decimal | None`. Both delegate to `to_decimal`.
- `require_bool(...) -> bool`. It rejects anything that is not a JSON bool.
- `require_int(...) -> int`. It accepts an int, or a `Decimal` with an integral value. It rejects `bool` and non-integral values.
- `require_list(payload, key) -> list[Any]`, `require_mapping(payload, key) -> Mapping[str, Any]`, `optional_utc(payload, key) -> datetime | None`, and `require_utc(...) -> datetime`. The last two go through `to_utc`.
- `epoch_ms_to_utc(value: object, field: str) -> datetime`. It takes an int or an integral `Decimal` of milliseconds and returns an aware UTC datetime.
- `api_time.to_api_time(value: datetime, field: str) -> str`.
  - A naive value raises `ValidationError(f"{field}: datetime must be timezone-aware")`.
  - Otherwise it returns `value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")`.

- [ ] **Step 1: Write the failing tests:**
  - `require_str({"a": 1}, "a")` raises `ResponseFormatError` and the message names `'a'`.
  - `require_int({"n": Decimal("2.5")}, "n")` and `require_int({"n": True}, "n")` raise.
  - `require_int({"n": Decimal("20")}, "n") == 20`.
  - `epoch_ms_to_utc(1647440528194, "t") == datetime(2022, 3, 16, 14, 22, 8, 194000, tzinfo=UTC)`.
  - `to_api_time(datetime(2022, 4, 1, 3, 1, tzinfo=timezone(timedelta(hours=2))), "start") == "2022-04-01T01:01:00"`.
  - `to_api_time(datetime(2022, 4, 1), "start")` raises `ValidationError`.
- [ ] **Step 2: Run** `pytest tests/unit/domain -q`. Expected: FAIL on an ImportError for the new names.
- [ ] **Step 3: Implement.** Switch `confirmation.py` to the shared helpers. Its existing tests are the refactor's safety net.
- [ ] **Step 4: Run** `pytest tests/unit -q`. Expected: all PASS.
- [ ] **Step 5: Commit.** `refactor(domain): share strict payload converters and add query-time formatting`

### Task 2: Selected account survives re-login; account switch

**Files:**
- Modify `src/capitalcom/application/session.py`.
- Create `src/capitalcom/application/login.py`, which takes the request building and response parsing out of `session.py` to keep it ≤300 lines.
- Tests: `tests/unit/application/test_account_switch.py`. Update the `login_ok` helpers in `tests/unit/**` so the login body carries `{"currentAccountId": "A"}`.

**Interfaces (Produces):**
- `login.parse_login(response: HttpResponse) -> Result[LoginGrant, CapitalComError]`.
  - `LoginGrant(cst: str, security_token: str, account_id: str)` must have both headers and a body `currentAccountId` that is a non-empty `str`. Anything else gives `ResponseFormatError`.
  - `LoginGrant`'s repr hides the tokens.
- `SWITCH_ALREADY_ACTIVE = "error.not-different.accountId"`. Task 7 pins the real value.
- `SessionManager.switch_account(account_id: str) -> Result[None, CapitalComError]`. Under the manager lock:
  1. An empty `account_id` gives `Err(ValidationError)`.
  2. Get the tokens, logging in if needed.
  3. If the current account already equals `account_id`, record it as selected and return `Ok` without a request.
  4. Otherwise send `PUT /api/v1/session {"accountId": account_id}` directly through the dispatcher, because `ApiClient` drops response headers. Then:
     - **Ok:** if the response carries both `CST` and `X-SECURITY-TOKEN`, adopt them as a new generation and register them for redaction. Set current and selected to `account_id` and mark the session used.
     - **400 with `SWITCH_ALREADY_ACTIVE`:** same as Ok. A retry after a lost response reached a session that had already switched.
     - **401:** drop the tokens and do one login targeting `account_id`.
     - **Any other error:** return it. The selection is unchanged.
- `SessionManager.current_account_id -> str | None`. This is a property read under the lock.
- `_login(target: str | None)`. After a successful `POST /session`, if `target` (by default the selected account) differs from the body's `currentAccountId`, it sends the switch with the new tokens before handing them out. If that switch fails, it drops the tokens and returns the error. A wrong-account token is never returned.

- [ ] **Step 1: Write the failing tests** using `FakeTransport` and `FakeClock`:
  - `test_switch_sends_put_and_records_account`.
  - `test_switch_to_current_account_sends_nothing`.
  - `test_switch_adopts_tokens_returned_by_put`: the next call sends the new `CST`.
  - `test_relogin_after_idle_reapplies_selected_account`: Review Focus 1. Advance the clock 600 s. The next call's requests are `POST /session` (body account A), then `PUT /session {"accountId": "B"}`, then the call itself.
  - `test_relogin_after_401_reapplies_selected_account`.
  - `test_failed_reapply_returns_error_and_hands_out_no_tokens`: the call itself is never sent.
  - `test_switch_answered_already_active_counts_as_success`: Review Focus 2.
  - `test_failed_switch_keeps_previous_selection`: a later re-login does not target the rejected id.
  - `test_login_without_current_account_id_is_response_format_error`.
- [ ] **Step 2: Run** `pytest tests/unit/application -q`. Expected: the new tests FAIL with `AttributeError` for `switch_account`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/unit -q`. Expected: all PASS, including the stage 1 session tests with the updated `login_ok`.
- [ ] **Step 5: Commit.** `feat(session): switch account and re-apply it after every re-login`

### Task 3: Encrypted-password login (`capitalcom[encryption]`)

**Files:**
- Create `src/capitalcom/infrastructure/rsa_password.py`.
- Modify `application/login.py`, `application/session.py`, `api/composition.py`, `api/client.py` and `pyproject.toml` (add `cryptography>=44.0.1` to the `dev` group).
- Tests: `tests/unit/infrastructure/test_rsa_password.py` and `tests/unit/application/test_encrypted_login.py`.

**Interfaces (Produces):**
- `PasswordEncryptor = Callable[[str, str, int], str]`, in `application/login.py`. Its arguments are `(password, encryption_key_b64, timestamp_ms)` and it returns the ciphertext as base64.
- `rsa_password.encrypt_password(password: str, encryption_key: str, timestamp: int) -> str`. These steps are documented by Capital.com's Java sample; padding and charset are designer's calls that the Task 7 demo login proves:
  1. `plain = base64(utf8(f"{password}|{timestamp}"))`.
  2. Load `encryption_key` as base64 DER SubjectPublicKeyInfo with `serialization.load_der_public_key`.
  3. Encrypt with RSA PKCS#1 v1.5 (`padding.PKCS1v15()`), then base64 the ciphertext.
  4. A key that will not load raises `ValueError`.
- `SessionManager(dispatcher, clock, credentials, encryptor: PasswordEncryptor | None = None)`. With an encryptor, **every** login, renewals included, does the following:
  1. Sends `GET /api/v1/session/encryptionKey` with only `X-CAP-API-KEY`.
  2. Reads `encryptionKey` (str) and `timeStamp` (int ms). Missing values or a `ValueError` from the encryptor give `ResponseFormatError`.
  3. Posts `{"identifier", "password": <ciphertext>, "encryptedPassword": True}`.
  4. Registers the ciphertext for log redaction.
- `build_core(..., encrypted_password: bool = False)` imports `rsa_password` only when `encrypted_password` is true. If `cryptography` is missing it raises `ImportError("encrypted_password=True needs the 'encryption' extra: pip install 'capitalcom[encryption]'")`.
- `CapitalCom(..., encrypted_password: bool = False)` passes the flag through, so a missing extra fails in the constructor.

- [ ] **Step 1: Write the failing tests:**
  - `test_encrypt_password_round_trips`: generate an RSA-2048 keypair in the test, encrypt, decrypt with the private key using PKCS1v15, and assert `b64decode(plain) == b"pw|1647440528194"`. PKCS#1 v1.5 output is random, so comparing ciphertexts would prove nothing.
  - `test_bad_key_raises_value_error`.
  - `test_encrypted_login_fetches_a_fresh_key_each_login`: with a stub encryptor, two logins produce two `GET /session/encryptionKey` calls, and the posted body has `encryptedPassword is True` and the stub's output as `password`.
  - `test_missing_extra_fails_in_constructor`: monkeypatch `sys.modules["cryptography"] = None` and drop any cached `capitalcom.infrastructure.rsa_password`. The constructor raises `ImportError` matching `capitalcom\[encryption\]`. This is Review Focus 3.
- [ ] **Step 2: Run** `pytest tests/unit -q -k "encrypt or extra"`. Expected: FAIL with ImportError or AttributeError.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/unit -q`. Expected: all PASS.
- [ ] **Step 5: Commit.** `feat(session): support RSA-encrypted password login via the encryption extra`

### Task 4: `cc.session` — info, server time, switch

**Files:**
- Modify `api/session_resource.py`, and `api/composition.py` (add `environment: Environment` to `Core`).
- Create `src/capitalcom/domain/account.py` (`SessionInfo`; Task 5 adds to it).
- Test: `tests/unit/api/test_session_resource.py`.

**Interfaces (Produces):**
- `SessionInfo.from_api(payload) -> SessionInfo`.
  - Required fields: `client_id`, `account_id`, `locale`, `currency`, `stream_endpoint` (all `str`) and `timezone_offset` (`Decimal`).
  - Plus `raw`.
- `SessionResource.info() -> SessionInfo`, from `GET /api/v1/session`.
- `SessionResource.server_time() -> datetime`. It sends `GET /api/v1/time` through `core.dispatcher`, not `core.api`, so it never logs in. It returns `epoch_ms_to_utc(serverTime)`.
- `SessionResource.switch_account(account_id: str) -> None`. It wraps `SessionManager.switch_account`. The docstring warns that requests in flight on other threads may run on either account.

- [ ] **Step 1: Write the failing tests:**
  - `test_server_time_does_not_log_in`: Review Focus 5. The only request is `GET /api/v1/time`, and the result is aware UTC.
  - `test_info_parses_session`.
  - `test_info_with_missing_account_id_raises_response_format_error`.
  - `test_switch_account_raises_typed_error_on_rejection`.
- [ ] **Step 2: Run** them. Expected: FAIL with AttributeError.
- [ ] **Step 3: Implement.** **Step 4: Run** `pytest tests/unit -q`. Expected: all PASS.
- [ ] **Step 5: Commit.** `feat(api): add session info, server time and account switch`

### Task 5: `cc.accounts`

**Files:**
- Modify `domain/account.py`.
- Create `api/accounts.py`, and wire `self.accounts` in `api/client.py`.
- Tests: `tests/unit/domain/test_account.py` and `tests/unit/api/test_accounts.py`.

**Interfaces (Produces):**
- `Balance(balance, deposit, profit_loss, available)`. All four are `Decimal`.
- `Account`:
  - Required: `account_id`, `account_name`, `account_type`, `status`, `currency` (`str`), `preferred` (`bool`), `balance` (`Balance`).
  - Optional: `symbol`.
  - Plus `raw`.
- `Leverage(current: int, available: tuple[int, ...])`, and `AccountPreferences(hedging_mode: bool, leverages: Mapping[str, Leverage], raw)`.
- `AccountsResource`:
  - `list() -> tuple[Account, ...]`, from `GET /api/v1/accounts`.
  - `preferences() -> AccountPreferences`.
  - `update_preferences(*, leverages: Mapping[str, int] | None = None, hedging_mode: bool | None = None) -> None`:
    - It sends `PUT /api/v1/accounts/preferences` with only the arguments given.
    - Neither argument given, or a leverage that is not an `int` (a `bool` counts as not an int), raises `ValidationError`.
    - A body whose `status != "SUCCESS"` raises `ApiError(200, None, <body text>)`.
  - `top_up(amount: Decimal | int) -> None`:
    - On `Environment.LIVE`, it raises `ValidationError` and sends nothing.
    - `abs(amount) > 400000` raises `ValidationError`.
    - It sends `POST /api/v1/accounts/topUp {"amount": amount}`.
    - `successful` other than `true` raises `ApiError`.

- [ ] **Step 1: Write the failing tests.** Use the documented sample payloads from the reference, with leverages `{"SHARES": {"current": 5, "available": [1, 2, 3, 5]}}`:
  - `test_top_up_on_live_sends_nothing`.
  - `test_top_up_out_of_range_raises`.
  - `test_update_preferences_sends_only_given_fields`.
  - `test_update_preferences_without_arguments_raises`.
  - `test_unknown_account_type_is_kept_as_string`.
- [ ] **Step 2: Run** them. Expected: FAIL. **Step 3: Implement.** **Step 4: Run** `pytest tests/unit -q`. Expected: all PASS.
- [ ] **Step 5: Commit.** `feat(api): add accounts namespace`

### Task 6: `cc.history`

**Files:**
- Create `domain/history.py` and `api/history.py`, and wire `self.history`.
- Tests: `tests/unit/domain/test_history.py` and `tests/unit/api/test_history.py`.

**Interfaces (Produces):**
- `Activity`:
  - Required: `date` (from `dateUTC`), `deal_id`, `type`, `status`.
  - Optional: `epic`, `source`.
  - Plus `raw`.
- `Transaction`:
  - Required: `date` (from `dateUtc`), `transaction_type`, `reference`, `size` (`Decimal`, sent as a string), `currency`.
  - Optional: `instrument_name`, `note`, `status`.
  - Plus `raw`.
- `history_params(start: datetime | None, end: datetime | None, last_period: timedelta | None, *, max_span: timedelta | None) -> dict[str, str]`. It is a pure domain function. It raises `ValidationError` in these cases:
  - `last_period` is combined with `start` or `end`.
  - `last_period` is under 1 s, or over `max_span` when one is given.
  - `start > end`.
  - `end - start > max_span`.
  - A datetime is naive (via `to_api_time`).
  
  It emits `from`, `to` and `lastPeriod` (whole seconds). Activity passes `max_span=timedelta(days=1)`. Transactions pass `None`, because no maximum is documented.
- `HistoryResource`:
  - `activity(*, start=None, end=None, last_period=None, detailed: bool = False, deal_id: str | None = None, fiql: str | None = None) -> tuple[Activity, ...]`. `detailed` is sent only when true. `fiql` is sent as `filter`.
  - `transactions(*, start=None, end=None, last_period=None, transaction_type: str | None = None) -> tuple[Transaction, ...]`. `transaction_type` is sent as `type`.

- [ ] **Step 1: Write the failing tests.** Cover each `ValidationError` case above, which is Review Focus 4, and assert `transport.requests == []` after each. Also:
  - `test_activity_sends_utc_range`: an aware `+02:00` start is sent as UTC.
  - `test_transaction_size_string_becomes_decimal`.
  - `test_unknown_activity_source_is_kept`.
- [ ] **Step 2: Run** them. Expected: FAIL. **Step 3: Implement.** **Step 4: Run** `pytest tests/unit -q`. Expected: all PASS.
- [ ] **Step 5: Commit.** `feat(api): add history namespace`

### Task 7: Exports, contract probes, ADR 0008, draft PR

**Files:**
- Modify `src/capitalcom/__init__.py`, which exports `SessionInfo`, `Account`, `Balance`, `AccountPreferences`, `Leverage`, `Activity` and `Transaction`.
- Create `tests/contract/test_session_extras_contract.py` and `tests/contract/test_accounts_history_contract.py`.
- Create `docs/adr/0008-session-context-and-read-models.md`.

- [ ] **Step 1: Write the contract tests.** Each logs what it observes at INFO.
  - `server_time()` is within 5 minutes of `datetime.now(UTC)`.
  - `info().account_id == core.session.current_account_id`.
  - **Encrypted login.** Build a second core with `encrypted_password=True` and `RetryPolicy(max_attempts=6, base_delay_s=1.0)`, because separate clients' logins can draw 429 (ADR 0007). Ping, then log out.
  - **Probe: switch to the already-active account.** Send a raw `PUT /api/v1/session` through the dispatcher, with the current id. Assert 400 and `errorCode == SWITCH_ALREADY_ACTIVE`, and log whether the response carried `CST`.
  - **Switch round trip.** Skip it when `accounts.list()` has a single account. Otherwise switch to the other account and back in `finally`, and log whether the tokens changed.
  - **Preferences round trip.** Read the preferences, write back identical `leverages` and `hedging_mode`, then read again and expect equality.
  - **History.** `history.activity(last_period=timedelta(hours=1))` and `history.transactions(last_period=timedelta(days=1))` return tuples.
- [ ] **Step 2: Write ADR 0008.** It records:
  - The selected account is re-applied after every re-login, and why.
  - Switch tokens are adopted from the `PUT` response.
  - RSA encryption is an infrastructure function injected into `SessionManager`. It is not a port, since there is no process boundary; it lives in infrastructure because `cryptography` is an optional third-party dependency the core allowlist forbids. A fresh key is fetched per login.
  - `/time` runs without auth.
  - Read models keep server enums as `str`, and only the UTC timestamp fields are parsed.
- [ ] **Step 3: Verify locally:** `ruff check . && ruff format --check . && mypy && pytest --cov=capitalcom && python -m build`. Then run Semgrep (`p/python`, `p/security-audit` and `p/secrets` at ERROR), and `superpowers:verification-before-completion`.
- [ ] **Step 4: Review.** Run `/code-review high` on `master..HEAD` and fix the confirmed findings with RED→GREEN.
- [ ] **Step 5: Push and open a draft PR.** It is titled "Stage 2: REST resources" and has no Claude attribution, so `contract.yml` runs the probes.
  - If an observed value differs from what was pinned (`SWITCH_ALREADY_ACTIVE`, the encryption padding or charset), change the constant or implementation and its unit test in one commit. Record it in ADR 0008.
- [ ] **Step 6: Hand over.** Write plan 2b on the same branch, using the 2a interfaces and the probe outcomes.
