# Stage 3 — Legacy Layer, Golden Suite and CHANGELOG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `capitalcom.client.CapitalClient` on the 2.x core so every 1.0.4 name keeps its signature and return shape, pin that with a golden suite, and record the deliberate changes.

**Architecture:**
- `client.py` keeps the class, the constants and `colored_log`. Helpers live in a new package `capitalcom/legacy/`, which is outside `LAYER_RANKS` and may import `api`, `application` and `domain`.
- The legacy client owns a `requests.Session`, builds a `Core` with it (`build_core(http_session=...)`), and delegates to the core.
- The golden suite is written first and run against the untouched 1.0.4 module, so it is a characterization of real 1.0.4 behaviour, not of our reading of it.

**Tech Stack:** Python ≥3.11, `requests`, pytest, `responses`.

**Spec:** `docs/superpowers/specs/2026-11-11-capitalcom-v2-design.md`: §2.2, §4, §6.5 and §7. Also ADR 0007 (the legacy partial-close endpoint closes the whole position; the position is `affectedDeals[0]`) and ADR 0010 (netting, rounding).

## Facts this plan relies on

- 1.0.4 (`src/capitalcom/client.py`, 286 lines):
  - It calls `logging.basicConfig` at import and colours messages with ANSI.
  - The constructor logs in.
  - `_request` re-checks `time.time() > token_expiry`, logs in again once on a 401, waits 1 s on a 429 (10 attempts in total), and returns the raw `requests.Response` for any other status.
  - `open_raw_position` posts `{epic, expiry: "-", direction, size, orderType: "MARKET", guaranteedStop: False, forceOpen: True}`, plus `stopDistance` and `profitDistance` when they are truthy. It then returns `affectedDeals[0].dealId` from `get_deal_by_ref(ref, retries=5, delay=0.1)`.
  - `get_deal_by_ref` retries on 404, on 400 `error.invalid.dealReference`, and on a 200 with no `affectedDeals`.
  - `close_position_by_id` sends `DELETE /api/v1/positions {dealId[, size]}` when `size` is truthy, and returns `"SUCCESS"` on a 200 without confirming.
  - `get_balance` falls back to `accounts[0]` and reads `available` from the account's top level.
  - The star import also leaked `requests`, `time`, `logging` and `random`.
- `test_trade` passes the dealId returned by `open_forex_position` to `close_position_by_ref`, which asks `/confirms/{dealId}`. Whether that resolves was never observed. If it does not, 1.0.4 logged an error and left the position open.
- `encode_json` passes floats through to `json.dumps`, as `requests` did in 1.0.4. `OrderRequest` refuses floats (ADR 0010).
- `SystemClock.sleep` calls `time.sleep`, so patching `time.sleep` silences waits in both 1.0.4 and the new layer.

## Rulings taken while planning (for the owner to accept)

1. **Golden suite = characterization.**
   - Kept rows are tests that pass on 1.0.4 (Task 1) and stay green through the rewrite.
   - Changed rows (spec §7 changes 1–5, ADR 0007, and rulings 7–10 below) get RED tests in the task that changes them.
2. **`_request` stays a raw escape hatch.** It must return a `requests.Response` for any status, so it sends through the shared session, not the dispatcher.
   - It takes tokens from the session manager and is throttled by the core's rate limiter.
   - It always sends `verify=True` and `allow_redirects=False`. A caller passing either keyword gets `ValidationError`.
   - The timeout is `(5.0, 15.0)` unless the caller gives one.
   - 401 and 429 are handled as in 1.0.4, and `requests` exceptions propagate as in 1.0.4.
3. **Opens send the 1.0.4 body exactly**, through `api.dealing.submit`, not `positions.open`.
   - `OrderRequest` would refuse floats such as `0.001 * 100000`.
   - Dropping `forceOpen`, `orderType` or `expiry` changes a request whose effect was never observed.
   - Confirmation uses the core confirmer (5 s) instead of 5 × 0.1 s.
4. **Returned id = `affectedDeals[0].dealId`** whatever its status, as in 1.0.4. An accepted deal with no affected deals (netting, ADR 0010) raises `CapitalComError("deal <ref> was accepted but opened no position (it netted against an open one)")`. 1.0.4 also raised there, after its retries ran out. It never returns a guessed id or `None`.
5. **A rounded size on a legacy open** returns the id and logs a WARNING with both sizes. `SizeAdjustedError` would break 1.0.4 code for a deal that is booked.
6. **`get_deal_by_ref(retries, delay)`** keeps its meaning:
   - at most `retries` polls, with `delay` seconds between them, through the core clock, then `ConfirmationTimeoutError`;
   - one poll is the confirmer's, made public as `DealConfirmer.poll`.
7. **Read-only names.** `api_key`, `login`, `password`, `session` and `base_url` become read-only properties, so assigning one raises `AttributeError` instead of being silently ignored. `repr()` shows only the host.
8. **Token attributes.**
   - `cst` and `security_token` setters push a new token pair into the session manager, and `None` drops it.
   - The `token_expiry` getter is the wall-clock time when the idle timer runs out, or `0` with no session.
   - Setting it to a past time drops the tokens. A future time is accepted, and the core keeps renewing on its own timer.
9. **`test_trade` closes by id** (`close_position_by_id`), so it can no longer leave a position open.
10. **Narrower exports and stricter top-up.**
    - `client.__all__` lists the six legacy names. The four stdlib modules are no longer re-exported.
    - `top_up_demo` raises `ApiError` when the answer says `"successful": false`; 1.0.4 returned `None` for that.
    - There are still no local environment or amount checks, so float amounts keep working.
11. **Deprecation warnings.** `DeprecationWarning` fires once per name per process, on the constructor and on every public method. `_headers` and `_request` are private and do not warn. The text is `"CapitalClient.<name> is deprecated and will be removed in 3.0; see <MIGRATION_URL>"`, where `MIGRATION_URL = "https://github.com/Akinzou/CapitalCom/blob/master/docs/migration.md"`. Task 6 writes that file, and stage 5 may move the link to the MkDocs site.
12. **Errors 1.0.4 raised without an HTTP status** become `CapitalComError`. One example is `"No accounts found."`.

## Global Constraints

- **Repo rules.**
  - The only dependency is `requests`.
  - Files are ≤300 lines.
  - Imports point inward, and `tests/architecture` stays green.
  - No Claude attribution.
  - No credentials, tokens, account ids or balances in fixtures or contract-test logs.
- **No breaking change** (spec §2.2, §4): every 1.0.4 call keeps its signature and return type. Anything else that changes needs a CHANGELOG line.
- **Fixtures** are synthetic shapes from ADRs 0007–0010. Tokens are `cst-1`/`tok-1`, ids are `P1`/`o_1`, and the account is `A`.
- **Contract tests** run on demo only, using BTCUSD at minimum size and the `btc` sweep fixture. They never call `list_accounts`, `get_balance`, `top_up_demo` or `test_trade`, because those log or move balances.
- **Command:** `pytest` means `.venv/Scripts/python.exe -m pytest -p no:cacheprovider`.

## Review Focus

1. **A caller passing `verify=False` or `allow_redirects=True` to `_request`** must not weaken TLS or send tokens to a redirect target. Pinned in Task 3.
2. **A legacy open whose POST times out** must raise `OutcomeUnknownError` after exactly one POST, never a second position. Pinned in Task 4.
3. **`close_position_by_id(id, size=0.5)`** must raise before sending anything, and `size=0` must stay a full close. Pinned in Task 4.
4. **Floats such as `0.001 * 100000` and `100 * 10**-5`** must reach the server exactly as 1.0.4 sent them. Pinned in Tasks 1 and 4.
5. **Credentials** must never appear in `repr(client)`, in log records, or in the text of a login error. Pinned in Task 3.

---

### Task 1: Golden suite of kept rows, run against 1.0.4

**Files:**
- Create `tests/legacy/golden/` with `__init__.py`, `conftest.py`, `payloads.py`, `test_session_rows.py`, `test_trading_rows.py` and `test_account_rows.py`.

**Interfaces (Produces):**
- **`conftest.py`:**
  - `api` is a `responses.RequestsMock(assert_all_requests_are_fired=False)` with the demo login `POST` answering `{"currentAccountId": "A"}` and the `CST: cst-1` / `X-SECURITY-TOKEN: tok-1` headers.
  - `slept` is an autouse fixture that patches `time.sleep` with a recorder and yields `list[float]`.
  - `legacy(demo: bool = True) -> CapitalClient` uses the key `gold-key-0001`, the login `me@example.com` and the password `gold-pw-0001`.
  - `sent(api)` gives `(method, url, json)` for each call after the login.
- **`payloads.py`:**
  - `confirm(ref="o_1", *, status="ACCEPTED", affected=(("P1", "OPENED"),), deal_id="D1", size=None) -> dict`;
  - `account(account_id, balance, currency="USD") -> dict`;
  - `position_row(deal_id, level) -> dict`, reusing `tests.unit.trading_payloads.position_item`.

- [ ] **Step 1: Write the kept-row tests.** Each one asserts 1.0.4 behaviour:
  - **Session rows:**
    - `test_constructor_logs_in_eagerly`: one login POST with `X-CAP-API-KEY` and the body `{identifier, password}`.
    - `test_login_failure_raises` (`pytest.raises(Exception)`).
    - `test_attributes_mirror_the_session`:
      - `cst == "cst-1"` and `security_token == "tok-1"`;
      - `base_url == DEMO`, and `session` is a `requests.Session`;
      - `abs(token_expiry - (time.time() + 600)) < 5`;
      - `_headers() == {"CST": "cst-1", "X-SECURITY-TOKEN": "tok-1"}`.
    - `test_live_flag_selects_the_live_host`.
    - `test_assigned_tokens_are_sent`.
    - `test_past_token_expiry_forces_a_login`: two logins.
    - `test_request_returns_the_raw_response_for_any_status`: a 404 comes back as a `requests.Response`.
    - `test_request_logs_in_again_once_on_401`.
    - `test_request_waits_on_429`: `1.0 in slept`, and the final status is 200.
    - `test_request_passes_params_and_json`.
    - `test_login_session_renews_tokens`.
    - `test_session_settings_reach_requests`: a header set on `client.session.headers` is sent.
    - `test_colored_log_logs_the_text_at_its_level`.
  - **Trading rows:**
    - `test_open_raw_position_returns_the_affected_deal_id`: `"P1"`, not `"D1"`.
    - `test_open_raw_position_sends_the_1_0_4_body`: the exact dict; with `stop_dist=0` and `profit_dist=None` neither key is sent.
    - `test_open_forex_position_scales_lots_and_pips`: `size == 0.001 * 100000` and `stopDistance == 100 * 10**-5`.
    - `test_get_deal_by_ref_waits_until_ready`: answers 404, then 400 `error.invalid.dealReference`, then `{dealReference, dealStatus: "ACCEPTED"}`, then complete.
    - `test_get_deal_by_ref_gives_up_after_retries`: with `retries=3`, exactly 3 GETs, then it raises.
    - `test_open_that_nets_raises`: affected `()`.
    - `test_trade_swallows_open_errors`: with a 500 it returns `None` and logs ERROR `"Failed to open position"`.
  - **Account rows:**
    - `test_get_open_positions_returns_raw_dicts_with_floats`.
    - `test_get_balance_picks_the_account_or_the_first`.
    - `test_get_balance_raw_shape`: `available` is `None` when absent at the top level.
    - `test_get_balance_without_accounts_raises`.
    - `test_list_accounts_returns_raw_dicts_and_logs_each`: one INFO record per account.
    - `test_list_accounts_empty_returns_empty_list`.
    - `test_top_up_demo_returns_none`.
    - `test_http_error_raises`.
- [ ] **Step 2: Run them against the untouched 1.0.4 module.** Run `pytest tests/legacy -q`. Expected: all pass. A test that fails here describes something other than 1.0.4: fix the test, never the module.
- [ ] **Step 3: Commit:** `test(legacy): pin the 1.0.4 contract with a golden suite`.

### Task 2: Core hooks the legacy layer needs

**Files:**
- Modify `application/session.py`, `application/dispatcher.py`, `application/confirmer.py` and `api/composition.py`, plus their unit tests (`test_session_api_client.py`, `test_dispatcher.py`, `test_confirmer.py`).

**Interfaces (Produces):**
- **`SessionManager`:**
  - `current_tokens() -> SessionTokens | None` never logs in.
  - `adopt_tokens(cst: str | None, security_token: str | None) -> None`:
    - with both values present it adopts them as a new generation, with `last_used = now`, registered as secrets, and `current_account = None`;
    - with either one `None`, it drops the tokens.
  - `idle_remaining_s() -> float | None` is `IDLE_TIMEOUT_S - (now - last_used)`, or `None` without tokens.
- **`Dispatcher.throttle(method: str, path: str) -> None`** waits on the rate limiter, as `send` does.
- **`DealConfirmer.poll(deal_reference: str) -> Result[DealConfirmation, CapitalComError] | None`** is the old `_check`, building its own path. `confirm` calls it.
- **`Core.clock: Clock`**, set by `build_core`.

- [ ] **Step 1: Write the failing tests:**
  - `test_current_tokens_does_not_log_in`;
  - `test_adopted_tokens_are_handed_out_and_masked` (a log record shows `***`);
  - `test_adopting_none_drops_the_session`;
  - `test_idle_remaining_counts_down` (FakeClock advance 100 → 500);
  - `test_throttle_waits_like_send`;
  - `test_poll_returns_none_while_pending`;
  - `test_core_exposes_its_clock`.
- [ ] **Step 2: Run `pytest tests/unit/application tests/unit/api -q`.** Expected: FAIL (`AttributeError`).
- [ ] **Step 3: Implement.** Expected: suite green.
- [ ] **Step 4: Commit:** `feat(core): expose token, throttle and poll hooks for the legacy layer`.

### Task 3: Legacy client: construction, attributes, `_request`

**Files:**
- Create in `capitalcom/legacy/`:
  - `__init__.py`;
  - `deprecation.py`, holding `MIGRATION_URL`, `warn_once(name: str, extra: str = "") -> None`, a registry `_warned: set[str]` and a lock, with `stacklevel=3`;
  - `wiring.py`, holding `LEGACY_TIMEOUT = (5.0, 15.0)` and `legacy_core(api_key, login, password, demo, session) -> Core`;
  - `raw_request.py`, holding `send_raw(core: Core, session: requests.Session, base_url: str, method: str, path: str, kwargs: dict[str, Any]) -> requests.Response`.
- Rewrite `client.py`:
  - `__all__`, the four constants with their 1.0.4 values, and `colored_log` (logger `capitalcom.client`, no ANSI);
  - `CapitalClient.__init__`, the properties of rulings 7–8, `__repr__`, `login_session`, `_headers`, `_request`, `lot_to_size` and `pips_to_profit_distance`.
  - The 1.0.4 trading and account methods stay verbatim for now; they call `_request`.
- Modify `pyproject.toml` to add `filterwarnings = ["ignore:CapitalClient:DeprecationWarning"]`.
- Create `tests/legacy/test_changes_session.py` for changed rows. The `deprecation._warned` registry is reset by a fixture.

- [ ] **Step 1: Write the failing tests:**
  - `test_import_configures_no_logging`: a subprocess runs `import logging, capitalcom; print(len(logging.getLogger().handlers))` → `0`.
  - `test_colored_log_has_no_ansi`.
  - `test_login_failure_is_authentication_error`: the message contains neither the password nor the key.
  - `test_constructor_and_methods_warn_once`: the URL is in the message, and a second call gives no warning.
  - `test_request_refuses_tls_and_redirect_overrides`: `ValidationError`, and nothing is sent beyond the login.
  - `test_request_has_a_timeout`: `req_kwargs["timeout"] == (5.0, 15.0)`.
  - `test_credentials_are_read_only_and_masked`: the `repr` lacks the key, password and login, and assignment raises `AttributeError`.
  - `test_token_attributes_round_trip_through_the_core`: setting a future `token_expiry` sends no new login, and `cst = None` causes a login on the next call.
  - `test_all_lists_the_legacy_names`.
- [ ] **Step 2: Run `pytest tests/legacy -q`.** Expected: the new tests FAIL, and the golden suite passes.
- [ ] **Step 3: Implement.**
  - On a login error, `__init__` logs `colored_log("ERROR", f"Login failed: {error}")`, then re-raises.
  - `login_session` drops the current tokens, then calls `tokens().unwrap()`.
  - `_request` warns nothing; it delegates to `send_raw`.
- [ ] **Step 4: Run `pytest -q` and `pytest tests/architecture -q`.** Expected: all green.
- [ ] **Step 5: Commit:** `feat(legacy): rebuild CapitalClient construction and raw requests on the core`.

### Task 4: Legacy trading methods

**Files:**
- Create `legacy/trading.py`, holding:
  - `open_body(epic, size, direction, stop_dist, profit_dist) -> dict[str, Any]`;
  - `affected_deal_id(confirmation: DealConfirmation) -> str`, per ruling 4;
  - `resolve_deal_id(core: Core, deal_reference: str, retries: int, delay: float) -> str`;
  - `warn_if_resized(requested: object, confirmation: DealConfirmation) -> None`.
- Modify `client.py`: `open_raw_position`, `open_forex_position` (its warning `extra` names the JPY flaw: pips × 1e-5 is wrong for JPY pairs, whose pip is 0.01), `get_deal_by_ref`, `close_position_by_id`, `close_position_by_ref` and `test_trade`.
- Test: `tests/legacy/test_changes_trading.py`.

- [ ] **Step 1: Write the failing tests:**
  - `test_full_close_uses_the_documented_endpoint_and_confirms`: `DELETE /api/v1/positions/P1`, a confirmation, then `"SUCCESS"`.
  - `test_rejected_close_raises`.
  - `test_partial_close_is_refused_before_sending`: `size=0.5` raises `ValidationError`, and `size=0` is a full close.
  - `test_rejected_open_raises_deal_rejected`.
  - `test_open_write_timeout_is_outcome_unknown`: `ReadTimeout`, then exactly one POST.
  - `test_netting_open_says_no_position_opened`.
  - `test_rounded_open_returns_the_id_and_warns`.
  - `test_trade_closes_by_id`: no `GET /confirms/P1`.
  - `test_forex_warning_names_jpy`.
  - `test_close_by_ref_resolves_then_closes`.
- [ ] **Step 2: Run `pytest tests/legacy -q`.** Expected: the new tests FAIL, and the golden suite passes.
- [ ] **Step 3: Implement.**
  - The open path: `submit(core, "POST", "/api/v1/positions", open_body(...))`, then `warn_if_resized`, then `affected_deal_id`.
  - Full close: `PositionsResource(core).close(deal_id)`.
  - `test_trade` sleeps through `core.clock`.
- [ ] **Step 4: Run `pytest -q`.** Expected: all green.
- [ ] **Step 5: Commit:** `feat(legacy): route legacy trading through confirmed core calls`.

### Task 5: Legacy account methods; lift the 1.0.4 exclusions

**Files:**
- Create `legacy/accounts.py`, holding `as_floats(value: Any) -> Any`, which turns `Decimal` into `float(repr)`-exact floats recursively.
- Modify `client.py`: `get_open_positions`, `get_balance`, `list_accounts` and `top_up_demo`.
- Modify `pyproject.toml`: remove the ruff `extend-exclude`, both mypy overrides for `capitalcom.client` and `tests.legacy.*`, and the coverage `omit`.
- Test: `tests/legacy/test_changes_accounts.py`.

- [ ] **Step 1: Write the failing tests:**
  - `test_http_errors_are_typed`: a 500 raises `ApiError`, and a 404 raises `NotFoundError`.
  - `test_no_accounts_is_capitalcom_error`.
  - `test_unsuccessful_top_up_raises`.
  - `test_floats_are_exact`: `as_floats(Decimal("1.0712")) == 1.0712`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** through `core.api.call(...).unwrap()` and `as_floats`. `list_accounts` logs via `colored_log` as 1.0.4 did.
- [ ] **Step 4: Run the full gate:** `ruff check .`, `ruff format --check .`, `mypy`, `pytest --cov=capitalcom -q` and Semgrep. Expected:
  - everything is clean, and coverage is at least 95%;
  - `client.py` is ≤300 lines;
  - the smoke tests pass unchanged.
- [ ] **Step 5: Commit:** `feat(legacy): finish CapitalClient on the core and type-check it`.

### Task 6: Contract round trip, ADR, CHANGELOG, migration guide

**Files:**
- Create `tests/contract/test_legacy_contract.py`, `docs/adr/0011-legacy-layer.md` and `docs/migration.md`.
- Modify `CHANGELOG.md` and spec §7.

- [ ] **Step 1: Write the contract test.** `test_legacy_round_trip(btc, demo_credentials)` does the following:
  - `CapitalClient(..., demo=True)` opens `float(btc.min_size)` BUY BTCUSD;
  - the returned id is among `get_open_positions()` dealIds;
  - `close_position_by_id(id) == "SUCCESS"`;
  - the id is then gone.
  - It logs only the confirmation status.
- [ ] **Step 2: Write the docs:**
  - **ADR 0011:** the decisions of rulings 1–12.
  - **`docs/migration.md`:** a table mapping each 1.0.4 call to its 2.0 equivalent.
  - **CHANGELOG:**
    - "Deprecated: `CapitalClient`";
    - "Changed (legacy)": changes 1–5 of spec §7, the partial-close refusal, and rulings 7, 9 and 10;
    - "overriding `_request` or `login_session` in a subclass is not supported";
    - a fix to the stale line "trading and market resources follow".
  - **Spec §7:** the partial-close bullet states the ADR 0007 result. Keep the spec ≤300 lines.
- [ ] **Step 3: Run `pytest -q` (the file-length test included).** Expected: green.
- [ ] **Step 4: Commit:** `docs: record the legacy layer (ADR 0011), changelog and migration guide; add legacy contract test`.
