# Stage 1b — Core: Adapters, Facade, Contract Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the stage 1a core to real HTTP behind a minimal `CapitalCom` facade (`cc.session` only). Then pin the undocumented API behaviour with contract tests against the demo account, including the partial-close probe that stage 3 depends on.

**Architecture:** `infrastructure/` implements the ports with `requests` and `time`. `api/composition.py` is the composition root (ADR 0003). The facade is the only place where a `Result` becomes an exception. The contract tests use the core directly, because the public positions API does not exist until stage 2.

**Tech Stack:** requests ≥2.32.3, the `responses` library, and GitHub Actions with repository secrets.

**Spec:** `docs/superpowers/specs/2026-11-11-capitalcom-v2-design.md` (§6.1, §6.3, §6.5, §7 partial close, §8). This plan continues `2026-11-11-stage-1a-core-domain-application.md` on the same branch.

## Global Constraints

- All stage 0 and stage 1a constraints apply.
- Contract tests talk **only** to `https://demo-api-capital.backend-capital.com`. The host is a literal in the test code, and no environment variable or option can change it.
- Secret values never appear in files, logs, fixtures, or test output. CI exposes the secrets only to the single test step that needs them.
- Every position a contract test opens is closed in a `finally` block through the documented `DELETE /api/v1/positions/{dealId}`.

## Review Focus

1. A caller injects a `requests.Session` with `verify=False`, or a server answers with a 302 to another host. TLS must still be verified, the redirect must not be followed, and the `CST` header must not leak. Pinned by Task 8.
2. `__exit__` runs while an exception is already propagating, and logout fails as well. The original exception must win, and the logout failure is logged at WARNING. Pinned by Task 9.
3. A contract run crashes midway. The positions it opened are still closed. Pinned by Task 10 through `try`/`finally`, and checked by asserting that no BTCUSD position opened by the run remains.
4. The nightly run hits a closed market. The test is reported as **skipped** with the market status, not as passed and not as red. Pinned by Task 10.
5. The confirmation `date` comes back without a timezone. The test pins whether it is UTC (within ±5 minutes of `now_utc`). Pinned by Task 10.

---

### Task 8: Infrastructure adapters

**Files:** Create `src/capitalcom/infrastructure/{__init__,requests_transport,system_clock}.py` and `tests/unit/infrastructure/test_adapters.py`.

**Interfaces (Produces):**
- `RequestsTransport(base_url: str, session: requests.Session | None = None, timeout: tuple[float, float] = (5.0, 15.0))`. It implements `HttpTransport`.
  - A `base_url` that does not start with `https://` raises `ValueError`.
  - It sends `data=encode_json(json)` with `Content-Type: application/json`.
  - It always passes `verify=True` and `allow_redirects=False`. Designer's call: following a redirect would resend the custom `CST` header, which `requests` does not strip, to the redirect target.
  - `ConnectTimeout` and `SSLError` give `TransportError(reached_server=False)`. Any other `RequestException` gives `reached_server=True`.
  - Error messages contain the method and path only.
- `SystemClock`: `time.monotonic`, `datetime.now(UTC)`, `time.sleep`.

- [ ] **Step 1: Write the failing tests** with `responses`:
  - A 200 JSON response maps to `HttpResponse`, with headers readable case-insensitively.
  - The body sent for `Decimal("0.001")` is `{"size": 0.001}`.
  - A `ConnectTimeout` gives `reached_server is False`. A `ReadTimeout` gives `True`.
  - A 302 is returned as a status-302 response with no second request.
  - `RequestsTransport("http://x")` raises.
  - A stub session whose `request(**kw)` records its kwargs, created with `verify=False`, still receives `kw["verify"] is True`.
- [ ] **Step 2: Run** the tests and expect FAIL. **Step 3: Implement.** **Step 4: Run** and expect PASS.
- [ ] **Step 5: Commit.** `feat(infrastructure): add requests transport and system clock`

### Task 9: Composition root, facade, public exports

**Files:**
- Create `src/capitalcom/api/{__init__,composition,client,session_resource}.py` and `tests/unit/api/test_facade.py`.
- Create `docs/adr/0005-error-model.md` and `docs/adr/0006-retries-and-idempotency.md`.
- Modify `src/capitalcom/__init__.py`, `pyproject.toml` (`[tool.coverage]`), and `.github/workflows/ci.yml` (coverage gate).

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces:
  - `Core(dispatcher, session: SessionManager, api: ApiClient, confirmer: DealConfirmer)`, a frozen dataclass.
  - `build_core(credentials: Credentials, environment: Environment, *, http_session: requests.Session | None = None, timeout=(5.0, 15.0), retry: RetryPolicy | None = None, confirm_timeout_s: float = 5.0, clock: Clock | None = None, transport: HttpTransport | None = None) -> Core`.
  - `CapitalCom(api_key: str, identifier: str, password: str, environment: Environment = Environment.DEMO, *, http_session: requests.Session | None = None, timeout=(5.0, 15.0), retry: RetryPolicy | None = None, confirm_timeout: float = 5.0)`:
    - An empty `api_key`, `identifier` or `password` raises `ValueError`.
    - `repr` is `CapitalCom(environment=Environment.DEMO)`; no identifier, because it is the user's e-mail.
    - `.session -> SessionResource`, with `ping() -> None` (`GET /api/v1/ping`) and `logout() -> None`.
    - `close()` is idempotent. It logs out only if a login happened, and raises if logout fails.
    - `__enter__` returns self. `__exit__` calls `close()`, but when an exception is already propagating, a logout failure is logged at WARNING and the original exception wins.
  - `capitalcom/__init__.py` keeps `from .client import *` first, so the legacy surface is unchanged. Then it exports `CapitalCom`, `Environment`, `Direction`, `RetryPolicy`, `DealConfirmation`, and every error class.
  - Coverage: `fail_under = 95`. Omit `*/capitalcom/client.py` until stage 3; the comment states that removal stage.

- [ ] **Step 1: Write the failing tests.** Use `build_core` with `FakeTransport` and `FakeClock`, and `responses` for one end-to-end facade case.
  - `with CapitalCom(...) as cc: cc.session.ping()` sends login, ping, and logout, in that order.
  - `CapitalCom("", "i", "p")` raises `ValueError`.
  - `"pw" not in repr(cc)`.
  - `__exit__` with a `RuntimeError` in flight plus a failing logout re-raises the `RuntimeError`, and `caplog` holds one WARNING.
  - `close()` twice sends one `DELETE /session`.
  - A facade with no calls closes without any request.
  - `from capitalcom import CapitalClient, CapitalCom, OutcomeUnknownError` works.
- [ ] **Step 2: Run** the tests and expect FAIL. **Step 3: Implement.** **Step 4: Run** `pytest --cov=capitalcom` and expect PASS with coverage ≥95%.
- [ ] **Step 5: Write the ADRs.**
  - ADR 0005, the error model: typed exceptions at the facade and `Result` inside; why the server errors subclass `ApiError`; the `Decimal` limit of 15 significant digits on the wire.
  - ADR 0006: the retry and idempotency matrix and the rate-limit buckets.
- [ ] **Step 6: Commit.** `feat(api): add CapitalCom facade with session namespace`

### Task 10: Contract tests on demo and the CI job

**Files:**
- Create `tests/contract/{__init__,conftest,test_session_contract,test_confirms_contract,test_partial_close_probe}.py`.
- Create `.github/workflows/contract.yml`.

**Interfaces:**
- Consumes: `build_core`, `Credentials`, `Secret`, `Environment.DEMO`.
- Produces the `conftest.py` fixtures:
  - `demo_core`:
    - It asserts `Environment.DEMO.rest_url == "https://demo-api-capital.backend-capital.com"` and builds the core with `Environment.DEMO`. No other environment is reachable from this file.
    - It reads `CAPITAL_API_KEY`, `CAPITAL_IDENTIFIER` and `CAPITAL_PASSWORD`. If they are missing it calls `pytest.fail` when `CI` is set, and `pytest.skip` otherwise.
    - It logs out on teardown.
  - `open_btc(size)`: opens a position and yields its dealIds. In `finally` it closes every affected dealId through the documented endpoint.
- Market: BTCUSD, which trades 24/7. Size: from `GET /api/v1/markets/BTCUSD`, `dealingRules.minDealSize.value` and `minSizeIncrement`. If `snapshot.marketStatus != "TRADEABLE"`, call `pytest.skip(f"BTCUSD {status}")`.
- Every module is marked `pytestmark = pytest.mark.contract`.

- [ ] **Step 1: Write the session contract tests.**
  - Login, then `GET /api/v1/ping` returns `{"status": "OK"}`.
  - `DELETE /api/v1/session` succeeds.
  - A second call after logout logs in again lazily.
- [ ] **Step 2: Write the confirmation contract tests.**
  - Open a position with min size BUY. `confirm()` gives `ACCEPTED`, `deal_id` is set, and `affected_deals` is non-empty.
  - `abs(conf.date - now_utc) < 5 min`. This pins the UTC assumption from Task 2.
  - `GET /api/v1/confirms/o_doesnotexist`: record the observed status and `errorCode` and assert them. This pins the pending signals the confirmer relies on (404, or 400 `error.invalid.dealReference`).
  - Pin whether `deal_id == affected_deals[0].deal_id`. Stage 3 legacy returns the latter.
  - Closing through `DELETE /api/v1/positions/{dealId}` and then confirming gives `ACCEPTED`.
- [ ] **Step 3: Write the partial-close probe**, `test_legacy_partial_close_endpoint_closes_only_part`.
  - Open size `2 × minDealSize`.
  - Send `ApiClient.call("DELETE", "/api/v1/positions", json={"dealId": id, "size": minDealSize})` and confirm.
  - `GET /api/v1/positions/{id}` must report size `== minDealSize`.
  - The `finally` block closes whatever remains.
- [ ] **Step 4: Run locally**, only if the owner exports the three variables in their own shell: `pytest -m contract -v`. Otherwise go straight to Step 6.
- [ ] **Step 5: Write `contract.yml`.**
  - Triggers: `pull_request` to `master` (never `pull_request_target`), `schedule: cron "17 3 * * *"`, and `workflow_dispatch`.
  - Job `if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository`.
  - `permissions: contents: read`.
  - `concurrency: {group: contract-demo, cancel-in-progress: false}`, so two runs never trade the same account at once.
  - Use Python 3.14 and run `pip install -e . --group dev`.
  - Only the final step gets `env:` with `CAPITAL_API_KEY: ${{ secrets.CAPITAL_API_KEY }}` and the other two secrets, and runs `pytest -m contract -v`.
  - **Owner prerequisite:** in branch protection, mark the checks `contract` and every `ci.yml` job as required on `master`.
- [ ] **Step 6: Commit and push the branch.** `test(contract): pin session, confirms and partial-close behaviour on demo`. The contract job runs on the PR.

### Task 11: Record the probe outcomes, verify, PR

**Files:**
- Create `docs/adr/0007-partial-close.md`.
- Modify `CHANGELOG.md`, and the contract or domain tests only if an assumption proved false.

- [ ] **Step 1: Read the contract job log.** For each pinned assumption, decide:
  - The UTC date. If it is false, change `to_utc` to the observed offset and change its unit test in the same commit.
  - The 404-while-pending behaviour.
  - The rejection `reason` key. If no rejection was observed, the ADR says so and the key stays an assumption.
- [ ] **Step 2: Handle the partial-close result.**
  - **If the probe passed:** ADR 0007 records that the undocumented endpoint closes partially as of today's date. Stage 3 keeps it for the legacy `size=` path.
  - **If it failed:** change the probe's assertion to pin the observed behaviour (full close, or an error with its `errorCode`), so the gate is green and documents reality. ADR 0007 records that legacy `close_position_by_id(id, size=...)` will raise `ValidationError` in stage 3. Never silently close the whole position.
- [ ] **Step 3: Verify locally** with `ruff check . && ruff format --check . && mypy && pytest --cov=capitalcom && python -m build`, then run `superpowers:verification-before-completion`.
- [ ] **Step 4: Review.** Run `/code-review high` on the branch diff and fix confirmed findings.
- [ ] **Step 5: Push and update the PR.**
  - The PR body covers the summary, the Semgrep MEDIUM findings with a decision for each, the probe outcomes, and links to ADRs 0005–0007.
  - Merge with a merge commit after `ci.yml` and `contract.yml` pass.
- [ ] **Step 6: Hand over to the next plan.** The stage 2 plan (REST resources; RSA login, account switch, `GET /session`, `/time`) is written only after this merge, because it builds on the real interfaces and on the probe outcome.
