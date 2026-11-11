"""Every hand-written tracked file stays at or under 300 lines."""

import subprocess
from collections.abc import Iterable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIMIT = 300
# Recorded HTTP fixtures and lockfiles are machine-produced, so a line cap would only force
# arbitrary splits; binaries have no meaningful line count.
EXEMPT_PREFIXES = ("tests/fixtures/",)
EXEMPT_SUFFIXES = (".lock", ".png", ".ico", ".jpg", ".gif", ".whl")


def oversized(paths: Iterable[Path], limit: int = LIMIT) -> list[tuple[Path, int]]:
    """Return ``(path, line_count)`` for every file longer than ``limit`` lines."""
    result = []
    for path in paths:
        count = len(path.read_bytes().splitlines())
        if count > limit:
            result.append((path, count))
    return result


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout.decode()
    names = [n for n in out.split("\0") if n]
    return [
        REPO / n
        for n in names
        if not n.startswith(EXEMPT_PREFIXES)
        and not n.endswith(EXEMPT_SUFFIXES)
        and (REPO / n).is_file()
    ]


def test_oversized_reports_301_line_file(tmp_path: Path) -> None:
    big = tmp_path / "big.md"
    big.write_text("x\n" * 301, encoding="utf-8")
    small = tmp_path / "small.py"
    small.write_text("x\n" * 300, encoding="utf-8")
    assert oversized([big, small]) == [(big, 301)]


def test_tracked_files_within_limit() -> None:
    offenders = oversized(_tracked_files())
    assert offenders == [], f"files over {LIMIT} lines: {offenders}"
