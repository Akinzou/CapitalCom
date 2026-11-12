# Stage 5 — Documentation, debt sweep and release 2.0: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every deferred defect, publish a documentation site whose examples cannot drift, and ship 2.0.0rc1 ready for PyPI.
**Architecture:** Debt fixes first (Tasks 1–7), because the docs describe post-fix behaviour. Then the docs toolchain (Task 8), executable examples and README (Task 9), the guides (Task 10) and the release plumbing (Task 11).
**Tech Stack:** Python 3.11+, requests, websockets>=15, pytest + responses, MkDocs 1.6 + Material 9.8 + mkdocstrings-python, GitHub Actions.
**Spec:** `docs/superpowers/specs/2026-11-12-stage-5-docs-release-design.md` (approved 2026-11-12).

## Global Constraints

- Commands run from the repo root:
  - `PY=.venv/Scripts/python.exe`
  - tests: `$PY -m pytest -p no:cacheprovider`
  - lint: `$PY -m ruff check .` and `$PY -m ruff format --check .`
  - types: `$PY -m mypy`
- Coverage `fail_under = 95`.
- Semgrep (`PYTHONUTF8=1 .superpowers/semgrep-venv/Scripts/semgrep scan --config p/python --config p/security-audit --config p/secrets --severity ERROR --error -q src tests docs`): ERROR findings block.
- No file over 300 lines (`tests/architecture/test_file_length.py`).
- Code, comments and docs are in English. A comment records a decision, not an action.
- Commits carry no Claude attribution: no `Co-Authored-By` line, no "Generated with" line.
- No account ids, balances, deal ids or tokens in examples, CI logs or the site. Contract tests use the demo host only.
- The package-root import `from capitalcom import X` keeps working for every name it exports today.
- Every behaviour fix gets a CHANGELOG entry under a new `### Fixed` heading of `[Unreleased] — 2.0.0`.

## Review Focus

1. **Quick start output in a public CI log.** It prints only the confirmation status and the booked size, never a deal id or position id: the contract job runs it. Task 9 test: `test_quickstart_prints_no_identifiers`.
2. **Give-up raised from `subscribe_quotes`.** The caller then iterates and must get the buffered events with no second error. Task 5 test: `test_give_up_in_subscribe_keeps_events_without_a_second_raise`.
3. **A request behind a delayed login.** A `GET` reserved while a login waits on `SESSION` must not overtake the login inside the `GENERAL` window. Task 1 test: `test_general_window_counts_the_delayed_login_at_its_send_time`.
4. **The site deploying before the package exists.** The Pages job runs only after `publish` succeeds. Task 11: `pages` job `needs: publish`.
5. **The malformed frame is the awaited ack itself.** The wait ends in an ack timeout, a reconnect and a `NETWORK` gap, and the stream does not close. Task 4 test: `test_malformed_ack_times_out_into_a_network_gap`.

---

### Task 1: Rate limits as sliding windows (spec §6.2 item 4)

**Files:**
- Modify: `src/capitalcom/application/rate_limiter.py`, `tests/unit/application/test_retry_rate_limiter.py`, `docs/adr/0006-retries-and-idempotency.md`, `CHANGELOG.md`.
- Callers of `TokenBucket`: `tests/unit/application/stream_support.py:35`, `tests/unit/application/test_confirmer.py:43`, `tests/unit/application/test_dispatcher.py:177`.

**Interfaces:**
- Produces:
  - `class SlidingWindow(limit: int, window_s: float)` with `earliest(t: float) -> float` and `record(t: float) -> None`;
  - `default_windows() -> dict[RequestKind, SlidingWindow]`;
  - `RateLimiter(clock, windows: Mapping[RequestKind, SlidingWindow] | None = None)`.
- Removes: `TokenBucket` and `default_buckets`. Grep the whole repo before deleting them and paste the result into the commit body.

- [ ] **Step 1: Write the failing tests.** All use `FakeClock`; times are relative to `clock.monotonic()` at the start.
  - `test_eleventh_general_request_waits_a_full_second`: 11 `acquire("GET", "/api/v1/markets")` with no clock advance. The first 10 sleep 0; the 11th makes `clock.sleeps[-1] == pytest.approx(1.0)`.
  - `test_no_window_ever_exceeds_its_limit`: 40 GETs mixed with 3 `POST /api/v1/session` and 5 `POST /api/v1/positions`. Record the send time of each (monotonic after acquire). For every send time `s`, assert:
    - `GENERAL` sends in `[s, s+1)` ≤ 10;
    - `SESSION` sends in `[s, s+1)` ≤ 1;
    - `TRADE` sends in `[s, s+0.1)` ≤ 1.
  - `test_general_window_counts_the_delayed_login_at_its_send_time`: a login at t=0, a second login (waits until t=1), then 10 GETs. The window covering [1, 2) holds at most 10 sends, the delayed login included.
- [ ] **Step 2: Run them.** Run `$PY -m pytest -p no:cacheprovider tests/unit/application/test_retry_rate_limiter.py -k "window or eleventh"`. Expected: FAIL. The eleventh request waits 0.1 s, and the window counts exceed 10.
- [ ] **Step 3: Implement.** Use the spec's three limits:
  - `GENERAL`: `SlidingWindow(10, 1.0)`;
  - `TRADE`: `SlidingWindow(1, 0.1)`;
  - `SESSION`: `SlidingWindow(1, 1.0)`.

  Each window keeps `deque(maxlen=limit)` of recorded send times, appended in non-decreasing order (FIFO per window, as the token bucket queued callers). `earliest(t)` returns `max(t, last recorded, times[0] + window_s if full)`.

  `acquire` works under the lock:
  1. Start from `t = now`.
  2. Repeat `t = max(w.earliest(t) for w in applicable)` until it no longer changes.
  3. `record(t)` in every applicable window.
  4. Sleep `t - now` outside the lock.

  Test helpers use `SlidingWindow(1_000_000, 1e-9)` as "unlimited".
- [ ] **Step 4: Run the whole suite.** Expected: PASS. Rewrite ADR 0006's rate-limit bullet: sliding windows, the send-time invariant, and FIFO per window. Add the changelog entry under "Fixed": "bursts above 10 requests/s now wait instead of drawing a 429".
- [ ] **Step 5: Commit.** `fix(rate-limit): count each limit as a sliding window at send time`.

### Task 2: Parsing messages (spec §6.2 item 5 and §6.3 item 7)

**Files:**
- Modify: `src/capitalcom/domain/account.py:110-116`, `src/capitalcom/application/login.py:33-55`.
- Tests: `tests/unit/domain/test_account.py`, `tests/unit/application/test_session_api_client.py` (wherever `parse_login` is tested; grep for it).

- [ ] **Step 1: Write the failing test** `test_leverage_without_current_reports_missing`. `Leverage.from_api({"available": [1, 2]}, "SHARES")` raises `ResponseFormatError`, and `str(err)` contains `leverages.SHARES.current` and `missing`.
- [ ] **Step 2: Run it.** Expected: FAIL, because the message says "expected an integer, got NoneType".
- [ ] **Step 3: Implement.** A missing or null `current` raises `format_error(f"{where}.current", "missing")`. In `parse_login`, read `currentAccountId` with `optional_str`, and keep the explicit rejection of `""`. The existing `parse_login` tests must stay green with equivalent messages (the field name and the problem both named).
- [ ] **Step 4: Run the suite.** Expected: PASS. Add a changelog line under "Fixed".
- [ ] **Step 5: Commit.** `fix(parsing): report a missing leverage as missing; login uses the shared readers`.

### Task 3: Protection values and `SizeAdjustedError` placement (spec §6.3 items 6 and 8)

**Files:**
- Modify: `src/capitalcom/domain/protection.py`, possibly `src/capitalcom/domain/errors.py` and `src/capitalcom/domain/confirmation.py`.
- Test: `tests/unit/domain/test_protection.py`.

- [ ] **Step 1: Write a characterisation test first** (it must pass before and after): `test_protection_values_keep_their_shape`. For each of `StopLoss(level=1)`, `StopLoss(distance=2, trailing=True)`, `TakeProfit(amount=3)`, assert `repr`, equality with an identically built value, `hash`, and `to_body()` against literal expected dicts. To prove the test can catch a change, temporarily swap one expected key, watch it fail, then restore it.
- [ ] **Step 2: Refactor.** Move the one-of-three storage and the `level` / `distance` / `amount` body branch into one private helper, `_amount_body(prefix: str, level, distance, amount) -> dict[str, Any]`, used by both `to_body` methods. Constructors, fields and slots stay unchanged.
- [ ] **Step 3: `SizeAdjustedError`.** Try moving it to `errors.py`.
  - If `tests/architecture/test_layers.py` or the import graph reports a cycle, keep it where it is. Add one docstring sentence naming the cycle (`errors` would import `confirmation`).
  - Either way, `from capitalcom import SizeAdjustedError` and `from capitalcom.domain.confirmation import SizeAdjustedError` both still work.
- [ ] **Step 4: Run the full suite and mypy.** Expected: PASS.
- [ ] **Step 5: Commit.** `refactor(domain): share the protection amount branches; settle SizeAdjustedError's home`.

### Task 4: A malformed frame never aborts an ack wait (spec §6.1 item 1)

**Files:**
- Modify: `src/capitalcom/application/stream_link.py`, `src/capitalcom/application/stream_session.py`.
- Test: `tests/unit/application/test_stream_gaps.py`, or a new `test_stream_malformed.py` if the gaps file would exceed 300 lines.

**Interfaces:**
- Produces: the link's buffer holds `Event | ResponseFormatError` in arrival order. `next_incoming()` returns `Err(ResponseFormatError)` when it reaches a buffered error. `drain()` hands both kinds over, and the session re-queues errors as `Err` items in order.

- [ ] **Step 1: Write the failing tests.** They use `FakeConnection`, `ack_frame` and `quote_frame` from `tests.fakes`, and `open_stream` / `next_value` from `stream_support`.
  - `test_malformed_frame_during_subscribe_is_raised_in_order`. The script is `["not json", ack_frame("1", {"GOLD": "PROCESSED"}), quote_frame("GOLD")]`.
    - `subscribe_quotes(["GOLD"])` returns `Ok(None)`.
    - The next `next_event()` is `Err(ResponseFormatError)`.
    - The one after it is `Ok(Quote)`.
  - `test_malformed_frame_during_resubscription_keeps_the_stream`. The first connection drops (`RESET`). The second answers with `"not json"` before its auto-ack. Then:
    - `next_event()` yields the `ResponseFormatError`;
    - the next call yields the `Gap`;
    - `stream.closed is False`.
  - `test_malformed_ack_times_out_into_a_network_gap`. The subscribe's only answer is `"not json"`; the second connection uses `auto_ack`. Then:
    - `subscribe_quotes` returns `Ok(None)`, because it was reconnected and resubscribed;
    - events are the format error, then a `Gap` whose `reason is GapReason.NETWORK`.
- [ ] **Step 2: Run them.** Expected: FAIL. The subscribe returns `Err(ResponseFormatError)`, and the resubscription case closes the stream.
- [ ] **Step 3: Implement.** In `StreamLink._route`, a `ResponseFormatError` from `decode_frame` is appended to the buffer instead of returned. That way `_await` and the keepalive drain keep waiting. `StreamSession` turns a buffered error into `Err` at its position.
- [ ] **Step 4: Run the stream tests, then the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit.** `fix(stream): a malformed frame is raised in order and never aborts an ack wait`.

### Task 5: Giving up keeps what was read (spec §6.1 item 2)

**Files:**
- Modify: `src/capitalcom/application/stream_session.py`, `src/capitalcom/api/stream.py`.
- Tests: the stream session tests and `tests/unit/api/test_stream.py`.

**Interfaces:**
- Produces: `StreamSession.closed` is `True` once the socket is closed for good. A new `StreamSession.exhausted -> bool` is `True` once closed with nothing left to deliver. `Stream.__next__` ends iteration on `exhausted`, not on `closed`. `StreamResource.connect()` keeps checking `closed`.

- [ ] **Step 1: Write the failing tests.**
  - `test_give_up_in_next_delivers_buffered_events_then_raises`. The first connection buffers two quotes, then `RESET`. Every reconnect fails. Through `Stream`, iteration yields both quotes, then raises `StreamError`, then `StopIteration`.
  - `test_give_up_in_subscribe_keeps_events_without_a_second_raise`. One quote is buffered and the link drops during `subscribe_quotes`. The reconnects fail, so `subscribe_quotes` raises `StreamError`. After that, `list(stream)` equals `[that quote]`.
  - `test_refused_resubscription_also_keeps_buffered_events`. As the first test, but the reconnect is answered with a refusal, so `SubscriptionError` is raised after the events.
  - `test_explicit_close_discards_buffered_events`. After `close()`, `list(stream) == []`.
  - `test_connect_allowed_after_give_up_while_events_remain`. `cc.stream.connect()` succeeds while the old stream still has events.
- [ ] **Step 2: Run them.** Expected: FAIL. Today `StreamError` comes first and the events are lost.
- [ ] **Step 3: Implement.** On give-up:
  - close the link;
  - set `_closed`;
  - keep `_ready`;
  - store the error as a pending item at the end of `_ready` when the give-up happened in `next_event`, but not when it happened in `_apply`, which returns it directly.

  `close()` called by the user still clears `_ready`. Use a private `_give_up(error)` so `close()` keeps its meaning.
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit.** `fix(stream): events read before a give-up are delivered before its error`.

### Task 6: Gap reasons (spec §6.1 item 3)

**Files:**
- Modify: `src/capitalcom/infrastructure/websocket_transport.py:125-129`, `src/capitalcom/application/stream_session.py` (`_reason` and the drop path), `docs/adr/0012-streaming.md` (Reconnects and gaps), `CHANGELOG.md` (one "Fixed" entry covering Tasks 4–6).
- Tests: `tests/unit/infrastructure/test_websocket_transport.py`, the stream gap tests.

- [ ] **Step 1: Write the failing tests.**
  - `test_close_started_by_us_is_not_reached_server`. Unit-test `_closed()` with `ConnectionClosed(rcvd=Close(1000, ""), sent=Close(1009, ""), rcvd_then_sent=False)`: `reached_server is False`. With `rcvd_then_sent=True` it is `True`, and with only `rcvd` set it is `True`.
  - `test_drop_after_an_account_switch_is_account_switched`. Use `open_stream(..., accounts=["A", "B"])`. Re-login the session to account B with no stream call in between (invalidate the tokens and call `session.tokens()`), then script `TransportError("closed", reached_server=True)`. The gap's `reason is GapReason.ACCOUNT_SWITCHED`.
- [ ] **Step 2: Run them.** Expected: FAIL. The first returns `True` for a close we started; the second gives `SERVER_CLOSED`.
- [ ] **Step 3: Implement.**
  - `_closed`: `SERVER_CLOSED` only when `closed.rcvd is not None and closed.rcvd_then_sent is not False`.
  - In the drop path of `_next_event` and `_apply`, a reconnect whose current account id differs from `self._account` (and is not `None`) uses `ACCOUNT_SWITCHED`.
  - Update the ADR 0012 reason bullet.
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit.** `fix(stream): label gaps by who closed the link and by account switches`.

### Task 7: Test debts (spec §6.4)

**Files:**
- Modify: `tests/legacy/test_smoke.py:32-35`, `tests/contract/conftest.py:113-131`, `tests/contract/test_trading_contract.py:80-84`.

- [ ] **Step 1: Version test.** Rename it `test_installed_version_matches_pyproject`. It reads `pyproject.toml` with `tomllib` (path from `Path(__file__).parents[2]`) and compares that to `importlib.metadata.version("capitalcom")`. Prove it can fail: point it at a wrong literal once and watch it fail, then restore.
- [ ] **Step 2: `btc_orders` fixture.**
  - List orders with `OrdersResource(demo_core).list()` and filter on `epic == EPIC`.
  - Cancel each order with `.cancel(order_id)` inside `try`.
  - Collect failures as `type(err).__name__` only, with no ids, and `pytest.fail` with the count after trying all of them.
- [ ] **Step 3: Size rules test.** Compute `off_grid = btc.min_size + increment / 2`, where `increment` comes from the details' size-increment rule, and `assert off_grid % increment != 0` before using it.
- [ ] **Step 4: Run** `$PY -m pytest -p no:cacheprovider tests/legacy tests/contract --collect-only -q` (contract tests only collect locally), then the unit suite. Expected: PASS.
- [ ] **Step 5: Commit.** `test: version from pyproject; contract cleanup tries every cancel; off-grid size asserted`.

### Task 8: Documentation toolchain and site skeleton (spec §5.1, §5.2, §5.5, §5.6 first bullet)

**Files:**
- Create: `mkdocs.yml`, `docs/index.md`, `docs/reference/*.md`, `docs/adr/0013-documentation-toolchain.md`, `tests/architecture/test_docstrings.py`.
- Modify: `pyproject.toml` (dependency group `docs`), `.github/workflows/ci.yml` (job `docs`).
- Move: `docs/migration.md` → `docs/guides/migration.md` (grep for links to it first).
- Create: `docs/changelog.md` and `docs/license.md` as `--8<--` includes of the root files.

- [ ] **Step 1: Write the failing test** `test_every_public_name_has_a_docstring`. It walks the package root's public names (`dir(capitalcom)`, skipping `_`-prefixed names and modules), and for classes, their public methods and properties. It also walks the namespace classes of `CapitalCom` (`SessionResource`, `AccountsResource`, …, `StreamResource`, `Stream`). It asserts that `inspect.getdoc` is non-empty for each, and lists every miss in the failure message.
- [ ] **Step 2: Run it.** Expected: FAIL, or PASS. If it passes, break one docstring temporarily to prove it fails, and ledger that. Then fill in every docstring it names.
- [ ] **Step 3: Toolchain and site.**
  - Dependency group `docs = ["mkdocs>=1.6,<2", "mkdocs-material>=9.8,<10", "mkdocstrings-python>=1.10"]`.
  - `mkdocs.yml`:
    - `site_url: https://akinzou.github.io/CapitalCom/`;
    - `strict: true`;
    - `exclude_docs: superpowers/`;
    - `pymdownx.snippets` with `check_paths: true`, plus `admonition`, `pymdownx.superfences`;
    - `mkdocstrings` handler `python` with `paths: [src]`.
  - Navigation as the spec §5.2 table. Use only features Zensical lists as supported.
  - Reference pages are one `::: capitalcom.<module>` block each.
  - CI job `docs`: install with `--group docs`, run `mkdocs build --strict`.
  - ADR 0013 records spec §5.1 verbatim in substance: the dated ecosystem facts, the choice, the Zensical follow-up before 2027-05-05, and the rejection of Sphinx.
- [ ] **Step 4: Run** `$PY -m mkdocs build --strict` and the suite. Expected: the build ends with no warnings, and the tests PASS.
- [ ] **Step 5: Commit.** `docs: MkDocs site skeleton, API reference and docstring gate (ADR 0013)`.

### Task 9: Examples as code, README and quick start (spec §5.4, §5.6, Review Focus 1)

**Files:**
- Create: `docs/examples/quickstart.py`, plus one example per guide (`sessions.py`, `markets.py`, `trading.py`, `errors.py`, `streaming.py`), `tests/unit/docs/test_examples.py`, `tests/contract/test_quickstart_contract.py`.
- Modify: `README.md` (rewritten), `pyproject.toml` (`[tool.mypy] files` gains `docs/examples`; ruff already covers it).

**Interfaces:**
- Produces: each example is a script with `def main() -> None` and an `if __name__ == "__main__": main()` guard. Credentials come from `os.environ["CAPITAL_API_KEY"]`, `["CAPITAL_IDENTIFIER"]` and `["CAPITAL_PASSWORD"]`, with `environment=Environment.DEMO` written explicitly. Sections for pages are marked with `# --8<-- [start:name]` and `# --8<-- [end:name]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_every_example_runs_against_the_fake_api` is parametrized over `docs/examples/*.py`. It sets the env vars with `monkeypatch` and serves the demo host with `responses`, reusing `tests/unit/market_payloads.py` and `trading_payloads.py`. It runs `runpy.run_path(path, run_name="__main__")`. For `streaming.py`, it patches the client's stream transport factory with `FakeStreamTransport`.
  - `test_readme_quickstart_is_the_example`: the first ```` ```python ```` block in `README.md` equals `docs/examples/quickstart.py` with the `__main__` guard removed. Write it as an exact text comparison.
  - `test_quickstart_prints_no_identifiers`: captured stdout contains none of the fake's deal reference, deal id or account id strings.
- [ ] **Step 2: Run them.** Expected: FAIL. The examples and the README block do not exist yet.
- [ ] **Step 3: Write the examples and the README.**
  - The quick start:
    1. opens `Decimal` min size on `BTCUSD`;
    2. prints the deal status and booked size;
    3. closes the position;
    4. prints the close status.
  - README structure:
    - badges;
    - one paragraph on what it is;
    - install: `pip install --pre capitalcom` with the extras;
    - the quick start;
    - a "Going live" note;
    - a "Coming from 1.x" link;
    - license.
  - All links are absolute (`https://akinzou.github.io/CapitalCom/...` or `https://github.com/Akinzou/CapitalCom/...`).
  - `tests/contract/test_quickstart_contract.py` runs the script with `runpy` against demo. It skips on a closed market through the existing `btc` fixture, and uses `btc_positions`-style cleanup.
- [ ] **Step 4: Run** the unit suite, `ruff`, and `mypy` (which now covers `docs/examples`). Expected: PASS.
- [ ] **Step 5: Commit.** `docs: executable examples, README rewritten around the checked quick start`.

### Task 10: Guides and the reliability page (spec §5.2, §5.3)

**Files:**
- Create: `docs/getting-started.md` and `docs/guides/{sessions,markets,trading,streaming,reliability}.md`.
- Modify: `mkdocs.yml` navigation.

- [ ] **Step 1: Write the pages from the examples.** Each code block is a `--8<--` section of a Task 9 example. Prose comes from the ADRs and the code, never from memory.
  - `getting-started.md` contains a `!!! warning` box on `Environment.LIVE`, and its install
    line is `pip install --pre capitalcom`, like the README's.
  - `reliability.md` covers every bullet of spec §5.3. Each guarantee ends with a source link (`[ADR 0006](../adr/0006-retries-and-idempotency.md)` or a test path).
  - Where an ADR and the code disagree, stop and ledger it as a finding. Do not write the claim.
- [ ] **Step 2: Run** `$PY -m mkdocs build --strict` and the file-length test. Expected: no warnings, PASS.
- [ ] **Step 3: Commit.** `docs: getting started, guides and the errors and reliability page`.

### Task 11: Release plumbing for 2.0.0rc1 (spec §5.6, §7)

**Files:**
- Modify: `pyproject.toml`, `CHANGELOG.md`, `.github/workflows/ci.yml` (job `build`), `.github/workflows/publish.yml`, `.github/workflows/contract.yml`.
- Create: `.github/workflows/pages.yml`.

- [ ] **Step 1: Metadata.** In `pyproject.toml`:
  - `version = "2.0.0rc1"`;
  - classifier `Development Status :: 5 - Production/Stable`;
  - `description = "Client for the Capital.com REST and WebSocket API (demo and live)"`;
  - `[project.urls]` adds `Documentation`, `Changelog` (`https://github.com/Akinzou/CapitalCom/blob/master/CHANGELOG.md`) and `Issues`.

  `test_installed_version_matches_pyproject` must pass after `pip install -e .`. The CHANGELOG heading stays `[Unreleased] — 2.0.0`.
- [ ] **Step 2: CI.**
  - In the `build` job, add `pip install twine` and `twine check --strict dist/*`.
  - `pages.yml` runs on `workflow_dispatch` and `workflow_call`. It builds with `--group docs`, then runs `actions/upload-pages-artifact` and `actions/deploy-pages`, pinned by SHA like the other actions. It has environment `github-pages` and job-level `pages: write` and `id-token: write`.
  - `publish.yml` gains a `pages` job: `needs: publish`, `uses: ./.github/workflows/pages.yml`.
  - `contract.yml` gains a `workflow_dispatch` input `pypi_version`. When it is set, a `smoke` job runs instead of the contract tests:
    1. create a clean venv;
    2. `pip install "capitalcom==${{ inputs.pypi_version }}"`;
    3. run `docs/examples/quickstart.py` and the legacy round-trip test against demo, with the same secrets step as today.
- [ ] **Step 3: Verify the workflows locally.** Run `$PY -c "import yaml,sys;[yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml`. Also run `python -m build` and `twine check --strict dist/*` locally. Expected: no error, `PASSED`.
- [ ] **Step 4: Run the full gate set** from Global Constraints. Expected: all green.
- [ ] **Step 5: Commit.** `build: 2.0.0rc1 metadata, README check, Pages publishing and the PyPI smoke job`.

**Not in this plan (spec §7 steps 2-4, after merge, each with the owner's consent):** push the
`v2.0.0rc1` tag, run the smoke job with `pypi_version=2.0.0rc1`, then a small PR (`2.0.0`,
changelog dated, `--pre` dropped) and the `v2.0.0` tag.
