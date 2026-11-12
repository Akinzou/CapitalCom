"""``OutcomeUnknownError`` is built only by ``outcome_unknown``, which chains the cause."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "capitalcom"
HELPER = SRC / "application" / "error_mapping.py"
# A call, not the class statement or a mention in an annotation or isinstance check.
_CALL = re.compile(r"(?<!class )\bOutcomeUnknownError\(")


def direct_constructions(text: str) -> list[int]:
    """Line numbers in ``text`` that call the ``OutcomeUnknownError`` constructor."""
    return [n for n, line in enumerate(text.splitlines(), 1) if _CALL.search(line)]


def test_the_check_finds_a_direct_construction() -> None:
    # The dispatcher's spelling before 2.0.1, which dropped the cause.
    assert direct_constructions("        return Err(OutcomeUnknownError(m, p))\n") == [1]
    assert direct_constructions("class OutcomeUnknownError(CapitalComError):\n") == []


def test_only_the_helper_constructs_it() -> None:
    # A site that builds the error itself can drop the cause again, and a caller then cannot
    # tell a timeout after the send from a 5xx answer (ADR 0006).
    offenders = {
        str(path.relative_to(SRC)): lines
        for path in SRC.rglob("*.py")
        if path != HELPER and (lines := direct_constructions(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}
