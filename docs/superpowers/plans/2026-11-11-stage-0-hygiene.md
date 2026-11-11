# Stage 0 — Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the unchanged 1.0.4 code into a `src/` layout and add tooling, CI gates, licence files, and the ADR log. Every later stage then lands behind green gates.

**Architecture:** No behaviour changes. `src/capitalcom/client.py` stays byte-identical to 1.0.4. Architecture tests are added now, so stage 1 code is checked from its first commit.

**Tech Stack:** Python ≥3.11, hatchling ≥1.27 (PEP 639), pytest, pytest-cov, responses, ruff, mypy, Semgrep 1.185, GitHub Actions, and PyPI Trusted Publishing.

**Spec:** `docs/superpowers/specs/2026-11-11-capitalcom-v2-design.md` (sections 5, 8, 9 stage 0, and 11).

## Global Constraints

- Python `>=3.11`. CI matrix: 3.11, 3.12, 3.13, 3.14.
- Runtime dependency: `requests>=2.32.3`. The designer picked this floor because 2.32.0 fixed `Session.verify=False` leaking across requests.
- Every tracked hand-written file has 300 lines or fewer: code, tests, docs, config, and these plans. Exempt: `tests/fixtures/**` (recorded HTTP), lockfiles, binary files.
- Code, identifiers, comments, and docstrings are in English. A comment records a decision ("A over B because B silently breaks C"), never a description of what the code does.
- Commits use the repo's local git identity. They carry **no** `Co-Authored-By` or "Generated with" trailers, even if a tool suggests them.
- Work on branch `rewrite/stage-0-hygiene`, created from `rewrite/v2-design`. It becomes one PR into `master`.
- Do not delete anything before running `git grep` across the whole repo. Paste the grep output into the commit body.
- The package version becomes `2.0.0.dev0`. The new licence metadata must never ship under a `1.0.x` version number.

## Review Focus

1. Someone runs `pip install` of the built wheel into a clean venv. `from capitalcom import CapitalClient` and `from capitalcom.client import CapitalClient` must both work, or every existing user breaks. Pinned in Task 4, CI job `build`.
2. A CRITICAL or HIGH Semgrep finding lands in a PR. CI must fail, not just report. Pinned in Task 4: the job exits non-zero on `--severity ERROR --error`.
3. A 301-line file is committed. The gate must catch it, including Markdown. Pinned in Task 2 by the unit test on a synthetic file.
4. An upward import is introduced in stage 1, for example `domain` importing `requests` or `application` importing `infrastructure`. The test must fail. Pinned in Task 2 by synthetic-package tests.
5. A fork PR runs CI. Without secrets it must still run every non-contract gate. Pinned in Task 4: `ci.yml` uses no secrets at all.

---

### Task 1: `src/` layout, packaging, legacy smoke tests

**Files:**
- Move: `capitalcom/` → `src/capitalcom/` (`git mv`, content unchanged)
- Modify: `pyproject.toml`
- Delete: `requirements.txt` (after grep: `pyproject.toml` becomes the single source of dependencies)
- Create: `tests/__init__.py` (empty), `tests/legacy/test_smoke.py`, `docs/adr/0001-record-architecture-decisions.md`
- Modify: `.gitignore`: keep the existing private-rules line and add the standard Python ignores (`__pycache__/`, `*.py[cod]`, `.venv/`, `dist/`, `build/`, `*.egg-info/`, `.coverage`, `htmlcov/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`). Without them the file-length check, which also scans untracked files, trips over build artefacts.
- Create: `.gitattributes` with `* text=auto eol=lf`. The owner works on Windows and CI runs on Linux; without it, line endings flip and file-length and format checks give different results on the two systems.

**Interfaces:**
- Produces: the installable package `capitalcom` from `src/`, and the `dev` dependency group (`pip install -e . --group dev`, pip ≥25.1).

- [ ] **Step 1: Write the failing smoke tests** in `tests/legacy/test_smoke.py`:

```python
def test_root_import_exposes_legacy_client() -> None:
    from capitalcom import CapitalClient

    assert CapitalClient.__module__ == "capitalcom.client"


def test_legacy_module_names_importable() -> None:
    from capitalcom.client import BLUE, GREEN, RED, RESET, CapitalClient, colored_log  # noqa: F401


def test_lot_to_size_unchanged() -> None:
    from capitalcom.client import CapitalClient

    client = CapitalClient.__new__(CapitalClient)  # skip eager login
    assert client.lot_to_size(2, 100000) == 200000
    assert client.pips_to_profit_distance(15, 4) == 15 * 10**-4
    assert client.pips_to_profit_distance(0, 4) is None


def test_version_is_v2_dev() -> None:
    from importlib.metadata import version

    assert version("capitalcom") == "2.0.0.dev0"
```

- [ ] **Step 2: Run and confirm the failure.** Run `python -m pytest tests/legacy -v`. Expected: FAIL, because `version()` returns `1.0.4` or the package is not installed in editable mode from `src/`.
- [ ] **Step 3: Move the code and rewrite `pyproject.toml`.**
  - Run `git mv capitalcom src/capitalcom`.
  - In `[build-system]`, require `hatchling>=1.27` with backend `hatchling.build`.
  - In `[project]`: `version = "2.0.0.dev0"`, `requires-python = ">=3.11"`, `dependencies = ["requests>=2.32.3"]`, and `[project.optional-dependencies] encryption = ["cryptography>=42"]`.
  - Classifiers: Python 3.11–3.14, `Typing :: Typed`, `Development Status :: 4 - Beta`.
  - `[dependency-groups] dev`: pytest, pytest-cov, responses, ruff, mypy, types-requests, build.
  - Leave `license` and `authors` untouched; Task 3 changes the licence, and the owner decides about the author typo.
  - In `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, `addopts = "-m 'not contract' --strict-markers"`, and the marker `contract: hits the real Capital.com demo API`.
- [ ] **Step 4: Delete `requirements.txt`.** Run `git grep -n "requirements.txt"` first and keep the output for the commit body. Then `git rm requirements.txt`.
- [ ] **Step 5: Reinstall and check the tests pass.** Run `python -m pip install -e . --group dev && python -m pytest tests/legacy -v`. Expected: 4 passed.
- [ ] **Step 6: Write ADR 0001** (Nygard format: Status, Context, Decision, Consequences). Decisions are recorded in `docs/adr/NNNN-kebab-title.md`, are never edited once accepted, and are superseded instead.
- [ ] **Step 7: Commit.** `git commit -m "build: move package to src layout, require Python 3.11"`, with the grep output from Step 4 in the body.

### Task 2: Lint, type, and architecture gates

**Files:**
- Modify: `pyproject.toml` (sections `[tool.ruff]` and `[tool.mypy]`)
- Create: `tests/architecture/__init__.py`, `tests/architecture/importgraph.py`, `tests/architecture/test_layers.py`, `tests/architecture/test_file_length.py`, `src/capitalcom/py.typed`
- Create: `docs/adr/0002-tooling-and-quality-gates.md`, `docs/adr/0003-layering-and-composition-root.md`

**Interfaces:**
- Produces:
  - `importgraph.build_graph(src_root: Path, package: str) -> ImportGraph`, a frozen dataclass with two fields:
    - `internal: dict[str, set[str]]`, mapping each module to the internal modules it imports;
    - `external: dict[str, set[str]]`, mapping each module to the top-level names of the third-party and stdlib modules it imports.
  - `importgraph.layer_violations(graph) -> list[str]`.
  - `importgraph.find_cycle(graph) -> list[str] | None`.
  - `test_file_length.oversized(paths: Iterable[Path], limit: int = 300) -> list[tuple[Path, int]]`.
- Layer ranks (ADR 0003):
  - `capitalcom.domain*` = 0, `capitalcom.application*` = 1, `capitalcom.infrastructure*` = 2, `capitalcom.api*` = 3.
  - The `capitalcom` root package and `capitalcom.client` = 4.
  - A module may import only modules of equal or lower rank. `api` is the composition root, so `api -> infrastructure` is allowed.
  - Forbidden in ranks 0–1: `requests`, `urllib3`, `cryptography`, `websocket`, `socket`, `time`. Time goes through the `Clock` port.

- [ ] **Step 1: Write the failing tests.**
  - Build each synthetic package under `tmp_path`.
  - `test_detects_upward_import`: `pkg/domain/a.py` does `from pkg.application import b`. Expect one violation that names both modules.
  - `test_detects_forbidden_third_party_in_domain`: `pkg/domain/a.py` does `import requests`. Expect one violation.
  - `test_detects_cycle`: `pkg/application/a.py` and `pkg/application/b.py` import each other. `find_cycle` returns both names.
  - `test_relative_imports_resolved`: `from ..domain import x` inside `pkg/application/m.py` resolves to `pkg.domain.x` or `pkg.domain`.
  - `test_type_checking_imports_count`: an import under `if TYPE_CHECKING:` still produces an edge.
  - `test_real_package_clean`: on `src/capitalcom`, no violations and no cycle.
  - `test_oversized_reports_301_line_file` and `test_tracked_files_within_limit`:
    - collect files with `git ls-files --cached --others --exclude-standard`;
    - exempt `tests/fixtures/`, `*.lock`, and the binary suffixes `.png .ico .jpg .gif .whl`.
- [ ] **Step 2: Run** `python -m pytest tests/architecture -v`. Expected: FAIL with `ModuleNotFoundError: importgraph`.
- [ ] **Step 3: Implement `importgraph.py`** with `ast` and `graphlib.TopologicalSorter`; a `CycleError` gives the cycle. Implement `oversized`. Both together come to about 120 lines.
- [ ] **Step 4: Configure ruff and mypy.**
  - ruff: `target-version = "py311"`, `line-length = 100`, `src = ["src", "tests"]`.
  - ruff select: `E,W,F,I,B,UP,S,N,SIM,RUF,DTZ,T20,BLE,PT,A,C4,RET,PTH,ANN`. For `tests/**`, ignore `S101,ANN`.
  - `extend-exclude = ["src/capitalcom/client.py"]`, with the comment "legacy 1.0.4 kept byte-identical; stage 3 rewrites it and removes this exclusion".
  - mypy: `strict = true`, `files = ["src", "tests"]`, plus an override for `capitalcom.client` with `ignore_errors = true` and the same comment.
- [ ] **Step 5: Run all gates.** Run `ruff check . && ruff format --check . && mypy && python -m pytest -v`. Expected: all green. Fix the formatting of new files only.
- [ ] **Step 6: Write ADRs 0002 and 0003.**
  - 0002 covers the tool choices and why: hatchling for PEP 639, a stdlib import-graph test instead of import-linter (no extra dependency, and cycle plus layer rules in one test), and the severity mapping.
  - 0003 covers the layer ranks, `api` as the composition root, and the forbidden imports.
  - This resolves the gap in spec §6, which listed `api -> application` but not the composition-root edge.
- [ ] **Step 7: Commit.** `git commit -m "build: add ruff, mypy and architecture gates"`.

### Task 3: Licensing and CHANGELOG

**Files:**
- Create: `LICENSE`, `LICENSE-ADDITIONAL-PERMISSION`, `CHANGELOG.md`, `docs/adr/0004-licensing.md`
- Modify: `pyproject.toml` (`license`, `license-files`, classifiers) and `README.md` (only the licence badge and the `## License` section)

- [ ] **Step 1: Write `LICENSE`.**
  - Download the text verbatim from `https://raw.githubusercontent.com/polyformproject/polyform-licenses/1.0.0/PolyForm-Noncommercial-1.0.0.md`.
  - Verify `sha256 = c0ea4a896d2c8c394b29f9427589996db826cd501c512279ff0ed3ef48fabbe5` before editing.
  - Append `Required Notice: Copyright (c) 2025-2026 Wiktor Jelen (https://github.com/Akinzou/CapitalCom)`.
- [ ] **Step 2: Write `LICENSE-ADDITIONAL-PERMISSION`.**
  - It grants a natural person the right to use the software to trade their own personal accounts, demo or live, including for profit.
  - It excludes use on behalf of others, inside a business, and in any distributed or hosted product.
  - Commercial licences are available from the owner on request, using the contact URL from `[project.urls]`.
  - Head the file with "This grant is additional to, and does not modify, the PolyForm Noncommercial License 1.0.0". **The owner reviews this text before merge.**
- [ ] **Step 3: Update `pyproject.toml`.**
  - Set `license = "LicenseRef-PolyForm-Noncommercial-1.0.0"` and `license-files = ["LICENSE", "LICENSE-ADDITIONAL-PERMISSION"]`.
  - Remove `License :: OSI Approved :: MIT License` and add no `License ::` classifier, because PEP 639 forbids mixing them.
- [ ] **Step 4: Build and inspect the metadata.**
  - Run `python -m build && python -m zipfile -l dist/*.whl`.
  - Unzip `*.dist-info/METADATA`. Expected: `License-Expression: LicenseRef-PolyForm-Noncommercial-1.0.0`, both `License-File:` lines, and `Requires-Python: >=3.11`.
- [ ] **Step 5: Write `CHANGELOG.md`** in Keep a Changelog format, with an `## [Unreleased] — 2.0.0` section.
  - Licence: "1.0.x carried conflicting licence metadata: the licence field and README said CC BY-NC 4.0 and the classifier said MIT. From 2.0.0 the terms are PolyForm Noncommercial 1.0.0 plus the additional permission in `LICENSE-ADDITIONAL-PERMISSION`." Make no claim about which licence applied to 1.0.x.
  - Note that Python <3.11 is no longer supported.
- [ ] **Step 6: Update the README** licence section and badge to match. Write ADR 0004 on licensing.
- [ ] **Step 7: Commit.** `git commit -m "chore: adopt PolyForm Noncommercial 1.0.0 with personal-trading grant"`.

### Task 4: CI and publishing workflows

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/publish.yml`
- Delete: `.github/workflows/python-publish.yml` (grep the README badge first and point it to `ci.yml`)

- [ ] **Step 1: Write `ci.yml`.**
  - Trigger on `pull_request` and on `push` to `master`. Set `permissions: contents: read`. Use no secrets. Each job runs `python -m pip install --upgrade pip` before `pip install -e . --group dev`, because `--group` needs pip ≥25.1.
  - Jobs:
    - `lint`: `ruff check`, then `ruff format --check`.
    - `types`: `mypy`.
    - `test`: matrix 3.11–3.14, running `pytest --cov=capitalcom --cov-report=term-missing`.
    - `semgrep`: `pip install semgrep==1.185.0`, then a blocking step and a reporting step (below).
    - `build`: `python -m build`, create a fresh venv, `pip install dist/*.whl`, then run `python -I -c "from capitalcom import CapitalClient; from capitalcom.client import CapitalClient"` from a directory outside the repo.
  - Semgrep blocking step: `semgrep scan --config p/python --config p/security-audit --config p/secrets --severity ERROR --error --metrics=off src`. Semgrep 1.185 knows only `INFO`, `WARNING` and `ERROR`; we treat ERROR as CRITICAL/HIGH.
  - Semgrep reporting step: `--severity WARNING` (MEDIUM), `continue-on-error: true`, with the output written to `$GITHUB_STEP_SUMMARY` so it can be copied into the PR description.
  - Pin the actions: `actions/checkout@v4` and `actions/setup-python@v5`.
- [ ] **Step 2: Write `publish.yml`.**
  - Trigger on `push` of tags `v*`, in `environment: pypi`, with `permissions: id-token: write, contents: read`.
  - Build, then run `pypa/gh-action-pypi-publish@release/v1`. No token.
  - **Owner prerequisite before the stage 5 release:**
    - add a trusted publisher on PyPI for `Akinzou/CapitalCom`, workflow `publish.yml`, environment `pypi`;
    - after the first OIDC release, delete the `PYPI_API_TOKEN` secret.
- [ ] **Step 3: Validate the workflows locally.** Run `python -c "import yaml,sys;[yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml`. Expected: no error. Install `pyyaml` in a temp venv if it is missing.
- [ ] **Step 4: Commit.** `git commit -m "ci: add quality gates and trusted publishing"`, with the badge grep in the body.

### Task 5: Verify, review, PR

- [ ] **Step 1: Run the local verification** and check that every command exits 0. Run `ruff check . && ruff format --check . && mypy && python -m pytest -v && python -m build`. Then run the skill `superpowers:verification-before-completion`.
- [ ] **Step 2: Review the branch diff with `/code-review high`.** Fix confirmed findings, each fix in its own commit.
- [ ] **Step 3: Push and open the PR.**
  - Run `git push -u origin rewrite/stage-0-hygiene`, then `gh pr create --base master`.
  - The PR body covers the summary, the Semgrep MEDIUM findings with a fix-or-debt decision for each, and the owner prerequisites (licence-grant review, PyPI trusted publisher).
  - No attribution footer.
- [ ] **Step 4: Merge.** Wait for every CI job to pass, then merge with a merge commit (no rebase).
