# 2. Tooling and quality gates

- Status: accepted
- Date: 2026-11-11

## Context

Version 1.0.4 had no tests, no linting, no type checking and no CI apart from a manual publish
job. The 2.0 rewrite needs gates that every pull request passes before merge, and that run the
same way on a contributor's machine as in CI.

## Decision

- **Build backend: hatchling ≥ 1.27.** It supports PEP 639 licence metadata
  (`license = "<SPDX expression>"`, `license-files`) and the `src/` layout without extra
  configuration.
- **Layout: `src/capitalcom`.** CI installs the package non-editably and tests import it from
  site-packages, so a module left out of the wheel fails the tests instead of shipping.
- **Lint and format: ruff.** One tool replaces flake8, isort, pyupgrade, bandit-style checks
  (`S`) and black. It also formats Python code blocks inside Markdown, which keeps the examples
  in the docs runnable-looking.
- **Types: mypy `--strict`** over `src` and `tests`. The `py.typed` marker is deferred until
  stage 3 types the legacy surface: shipping it while `CapitalClient` is unannotated would turn
  every legacy call into a `no-untyped-call` error for users who run mypy strictly.
- **Tests: pytest** with pytest-cov. Contract tests against the live demo API carry the
  `contract` marker and are excluded from the default run.
- **Static analysis: Semgrep 1.185** with the `p/python`, `p/security-audit` and `p/secrets`
  rulesets. Semgrep's CLI reports three severities: `ERROR`, `WARNING` and `INFO`. `ERROR`
  findings are treated as critical/high and fail the build; `WARNING` findings are treated as
  medium and are listed in the pull request with a fix-or-accept decision.
- **Architecture: a stdlib import-graph test** (`ast` + `graphlib`) instead of import-linter.
  It enforces layering and acyclicity in one test without another dev dependency (ADR 0003).
- **File length: at most 300 lines** for every tracked hand-written file, enforced by a test.
  Recorded HTTP fixtures, lockfiles and binaries are exempt.
- **Line endings: LF** for all text files (`.gitattributes`), so the line-count and format
  checks give the same result on Windows and in CI.

The legacy 1.0.4 module `capitalcom/client.py` is excluded from ruff and mypy until stage 3
rewrites it on top of the new core. The exclusions carry comments naming that stage.

## Consequences

- Contributors run `pip install -e . --group dev` (pip ≥ 25.1) and the same commands CI runs.
- Semgrep's three-level scale is coarser than critical/high/medium/low. If a future Semgrep
  release exposes finer severities, this mapping is revisited in a new ADR.
