# capitalcom 2.0 — Documentation, debt sweep and release (stage 5)

Status: draft · Date: 2026-11-12 · Branch: `rewrite/stage-5-docs-release`
Extends `2026-11-11-capitalcom-v2-design.md` (§9 stage 5) and
`2026-11-12-streaming-addendum.md`. Where they disagree, this document wins for stage 5 only.

## 1. Intent

The reader is someone writing a bot or a script who wants to place trades on Capital.com from
Python: a classic API wrapper, not a framework. Within five minutes of finding the project
they should have installed it, logged in to a demo account, opened and closed a position, and
know how to point the same code at a live account.

They may run it with real money. The documentation therefore has to say what happens when
things go wrong, not only how things work when they go right. Every known defect left over
from stages 2 to 4 is fixed before the version number says "stable".

## 2. Goals

1. A README that works: every line of its quick start runs as written.
2. A documentation site (MkDocs) with a quick start, task guides, a page on errors and
   reliability, an API reference generated from docstrings, the 1.x migration guide, and the
   design decisions (ADRs).
3. Every documented code example is checked by the same gates as the library, and the quick
   start runs against the demo server.
4. Every deferred minor still present in the code is fixed (§6).
5. Release 2.0.0 on PyPI, after a release candidate.

## 3. Non-goals

- New API features. The only behaviour changes are the defect fixes in §6.
- Versioned documentation (a selector for 2.0, 2.1, …). The site documents the latest
  release; the changelog covers older ones.
- Translations. Documentation is in English, like the code.
- A tutorial on trading or on Capital.com itself. Links to Capital.com's own pages suffice.

## 4. Anti-goals

- A guarantee written in the documentation that no test or ADR backs. A reader risking money
  trusts the documentation more than the code; a promise the code does not keep is worse than
  silence.
- Examples that drift from the API. The current README imports a module that does not exist
  (`capitalcom_client`) and contains a duplicated, truncated block; that must not be possible
  again.
- Secrets in examples, logs or the published site. Examples read credentials from the
  environment (`CAPITAL_API_KEY`, `CAPITAL_IDENTIFIER`, `CAPITAL_PASSWORD`).
- A published site or README that documents 2.0 while `pip install capitalcom` installs 1.0.4.

## 5. Documentation

### 5.1 Toolchain (my call, recorded in a new ADR 0013)

MkDocs 1.6 with Material for MkDocs 9.8 and `mkdocstrings-python`, pinned below MkDocs 2
(`mkdocs>=1.6,<2`), in a `docs` dependency group. The ADR records the ecosystem as read on
2026-11-12:

- Material for MkDocs is in maintenance mode. Its release notes say: "Material for MkDocs
  reaches end of life on May 5, 2027. Critical fixes and security updates continue until that
  date." Its team now builds Zensical.
- MkDocs 2.0 has no announced release date. It is incompatible with Material and drops
  plugins.
- mkdocstrings is in maintenance mode too. Zensical supports it (since 0.0.11), so the API
  reference engine is the same on either path.
- Zensical reads `mkdocs.yml` but is pre-1.0.

MkDocs 1.6 + Material is chosen because:

- `mkdocs build --strict` gives a broken-link gate today;
- the stack is mature;
- the pin keeps a MkDocs 2 release from breaking the build.

The site configuration stays inside what Zensical documents as compatible. Moving to Zensical
before May 2027 then changes the build command and dependencies, not the pages; the ADR names
that move as a known follow-up.

Sphinx was rejected: it would mean rewriting the existing Markdown docs and ADRs for no gain
the reader sees.

### 5.2 Site layout

| Page | Content |
|---|---|
| Home | What the library is, install (extras `[streaming]`, `[encryption]`), the quick start, links |
| Getting started | API key and demo account on Capital.com, credentials from the environment, first trade, switching to live (`Environment.LIVE`) with a warning box |
| Guides: sessions and accounts | Lazy login, renewal, `with` / `close()`, accounts, switching account, history |
| Guides: markets and prices | Search and browse, market details, historical prices, sentiment, watchlists |
| Guides: trading | Positions and working orders, `StopLoss` / `TakeProfit`, confirmations, `Decimal` sizes (`Decimal(str(x))`), sizes the server rounds (`SizeAdjustedError`), netting |
| Guides: streaming | Quotes and OHLC bars, `Gap` events, limits, threading model, reconnects |
| Errors and reliability | See §5.3 |
| Migration from 1.x | Current `docs/migration.md`, moved into the site |
| API reference | Generated from docstrings: package-root names, `CapitalCom` and every namespace |
| Design decisions | The ADRs, unchanged |
| Changelog, license | `CHANGELOG.md`, `LICENSE` and the additional permission |

`docs/superpowers/` is excluded from the site.

### 5.3 Errors and reliability page

This page is the reason the site exists for a reader with real money. It covers:

- the exception hierarchy under `CapitalComError`, and what each class means for an open
  trade;
- which calls the library retries itself and which it deliberately does not;
- what to do on `OutcomeUnknownError`, `SizeAdjustedError`, `DealRejectedError` and
  `ConfirmationTimeoutError`, each with a short recipe;
- timeouts, rate limits and `429` handling;
- session renewal;
- TLS (always verified, CA bundle for proxies);
- token masking in logs;
- thread safety of `CapitalCom` and of `Stream`.

Every statement cites the ADR or test that backs it. Where the builder finds a gap between
what the ADRs say and what the code does, that is a defect: fix it under §6 or leave the
claim out. It is never papered over in prose.

### 5.4 Examples are code

- Examples live as files in `docs/examples/*.py` and are pulled into pages with
  `pymdownx.snippets`. Inline fragments of one or two lines that name a call may stay inline.
- `ruff check`, `ruff format --check` and `mypy --strict` cover `docs/examples/`.
- Every example runs in the unit suite against the existing fakes, with no network.
- The README quick start is the text of `docs/examples/quickstart.py`, embedded literally
  because PyPI cannot follow includes. A unit test asserts that the two match.
- The contract job runs `quickstart.py` against the demo server. It skips cleanly when the
  market is closed, as the trading contract tests already do.
- Links in the README are absolute, so they work on PyPI.

### 5.5 Docstrings

The API reference is only as good as the docstrings. A test asserts that each of these has a
docstring:

- every name exported from the package root;
- every public method and property of those names;
- every public method and property of the `CapitalCom` namespaces.

The builder fills in whatever that test finds missing.

### 5.6 Build and hosting

- CI gets a `docs` job running `mkdocs build --strict`. Broken links and unresolved
  references fail it.
- A separate workflow publishes the site to GitHub Pages through the official Pages actions.
  - It runs on a pushed final release tag (`v*` without a pre-release suffix), and on manual
    dispatch from `master` for documentation fixes between releases.
  - Only that job gets `pages: write` and `id-token: write`.
  - Deploying on every push to `master` was rejected: the site would document 2.0 while
    `pip install capitalcom` still installs 1.0.4.
- The owner enables Pages with source "GitHub Actions" in the repository settings, once.
- The site URL goes into `[project.urls]` as `Documentation`.
- The 300-line limit applies to every page and example. The existing file-length test
  already covers tracked files.

## 6. Debt sweep

Every item below was confirmed present in the code on 2026-11-12.

- Behaviour fixes are test-first, and each gets a changelog entry.
- Pure refactors keep the suite green and change no public behaviour.
- The sweep lands before the reliability page (§5.3) is written, because that page describes
  the behaviour after the fixes.

**Checked and already gone:**

- `comma_list` joining strings;
- the range check in `browse()` and `price_params` (both use `bounded_int`);
- where `caller_quantity` lives;
- the duplicated `status == SUCCESS` check (one helper in `parsing`);
- the duplicated `from`/`to` formatting (`window_params`);
- the whitespace-only watchlist name.

**Checked and kept:** `OrderRequest` and `WorkingOrderRequest` call `protection_body` and
`to_api_time` twice: once to validate at construction, once to build the body. Validating early
is the point, and caching the result would add state that brings the reader nothing.

### 6.1 Streaming (behaviour)

1. **Malformed frames.** A frame that cannot be decoded never aborts an acknowledgement wait,
   whether during a subscribe or during a reconnect's resubscription.
   - The wait goes on.
   - The `ResponseFormatError` is queued in arrival order, and `next()` raises it at that
     position.
   - Iteration may continue afterwards, as it already may for a malformed frame read outside
     an acknowledgement wait.
   - If the malformed frame was the awaited acknowledgement itself, the wait ends in the
     acknowledgement timeout and a reconnect with a `NETWORK` gap. That is the intended
     outcome, since the answer cannot be known.

   Today such a frame aborts the subscribe, and during a reconnect it closes the stream for
   good.
2. **Giving up keeps what was read.** The stream gives up after five failed reconnects, or on
   a refused login or key during resubscription. When it does:
   - the socket closes at once and `stream.closed` is `True` from then on;
   - a new `cc.stream.connect()` is allowed, since the old stream holds no socket;
   - the events read before the drop stay deliverable;
   - if the give-up happened inside `next()`, `next()` returns the buffered events first, then
     raises the error, then ends iteration;
   - if it happened inside `subscribe_*()` or `unsubscribe_*()`, that call raises the error.
     `next()` afterwards returns the buffered events and then ends iteration, without raising
     the same error a second time;
   - an explicit `close()` still discards buffered events, because the caller asked for it.

   Today `close()` inside the give-up clears the buffer before the error is returned.
3. **Gap reasons.** A gap is labelled:
   - `SERVER_CLOSED` only when the server sent its close frame first;
   - `NETWORK` when our side started the close, for example the WebSocket library closing on a
     protocol error;
   - `ACCOUNT_SWITCHED` when the drop came after the session moved to another account, even
     if the switch was made from another thread.

   ADR 0012 is updated to match.

### 6.2 REST (behaviour)

4. **Rate limiter.** The `GENERAL` bucket is charged when a slot is reserved, not when the
   request is sent. A login held back by the `SESSION` bucket can therefore make 11 requests
   in one second and draw a `429`.
   - Invariant after the fix, measured at send time on the clock port: no bucket ever sends
     more requests in any 1-second span than its limit, including when a login is delayed by
     the `SESSION` bucket.
   - A test drives that case.
   - ADR 0006 is updated.
5. **Missing leverage field.** A missing `Leverage.current` reports "expected an integer, got
   NoneType". It must report the field as missing, like every other required field.

### 6.3 Internal quality (no behaviour change)

6. `StopLoss` and `TakeProfit` duplicate the one-of-three storage and the `to_body` branches.
   Factor that out without changing their constructors, fields, equality or `repr`.
7. `parse_login` hand-rolls the `currentAccountId` check. Use the `parsing` helpers, with
   equivalent error messages.
8. `SizeAdjustedError` lives in `confirmation.py` to avoid an import cycle.
   - If it can move to `errors.py` without a cycle, move it.
   - Otherwise its docstring records why it stays.
   - `from capitalcom import SizeAdjustedError` works either way.

### 6.4 Tests

9. The contract fixture `btc_orders` stops at the first failed cancel and uses raw dicts. It
   should attempt every cancel, report all failures, and use `cc.orders`.
10. `test_position_size_rules` assumes `min_size * 1.5` is off the size grid. Assert that, or
    derive an off-grid size from the market's rules.
11. `test_version_is_v2_dev` hard-codes `2.0.0.dev0`. Compare the installed version with
    `pyproject.toml` instead.

## 7. Release (my call: a release candidate first)

1. **Package metadata.**
   - Version `2.0.0rc1`.
   - Classifier `Development Status :: 5 - Production/Stable`.
   - A description that mentions the WebSocket.
   - `[project.urls]` with `Documentation`, `Changelog` and `Issues`.
   - The changelog lists the §6.1 and §6.2 fixes.
2. **README rendering check.** `twine check --strict` runs in CI on the built distribution,
   so the README renders on PyPI.
3. **README install line.** Until `2.0.0` is out, it reads `pip install --pre capitalcom`, so
   a reader on GitHub does not get 1.0.4 under a 2.x quick start. The final-release PR drops
   `--pre`.
4. **Release candidate.** After the stage 5 PR merges, and only with the owner's consent, the
   `v2.0.0rc1` tag is pushed and the existing publish workflow uploads it.
   - `pip install capitalcom` does not pick up a pre-release, so 1.x users are untouched.
   - The trusted publisher on PyPI must be set up first. That step is the owner's.
5. **Smoke test on the published package.** A manually dispatched job in the contract
   workflow installs a given version from PyPI into a clean environment. It then runs the
   quick start and the legacy round trip against demo.
6. **Final release.** If the smoke test passes, a small PR does three things:
   - sets the version to `2.0.0`;
   - dates the changelog;
   - drops `--pre` from the README.

   After it merges, and with the owner's consent, the `v2.0.0` tag is pushed, which also
   publishes the site. A failure is fixed and shipped as `rc2`, not as `2.0.0`.

Why a candidate comes first:

- PyPI never lets a version be re-uploaded.
- A packaging mistake in `2.0.0` itself would reach every unpinned 1.x user on their next
  upgrade.
- It could then only be fixed with a `2.0.1`.

## 8. Constraints

- Branch `rewrite/stage-5-docs-release` and one PR. The flow is the same as every stage:
  local gates, then review, then PR, then green CI and contract runs.
- Merging and every tag push need the owner's consent.
- The gates are the same as before:
  - `ruff check .` and `ruff format --check .`;
  - `mypy --strict`;
  - `pytest` with coverage `fail_under = 95`;
  - Semgrep: ERROR findings block, WARNING findings are reported in the PR;
  - the file-length test.
- No account ids, balances, deal ids or tokens in CI logs, examples or the site.
- Contract runs use the demo host only.

## 9. Left to the builder

- Wording and order of the pages, beyond §5.2 and §5.3.
- Theme settings: colours, navigation tabs, search.
- Which demo market the quick start trades, as long as its contract run skips cleanly when the
  market is closed.
- The exact mechanism for §6.1 and for §6.2 item 4, as long as the behaviour above holds and
  the ADRs are updated.
- How the docs examples fake the server: the existing `tests/fakes.py` or `responses`.
