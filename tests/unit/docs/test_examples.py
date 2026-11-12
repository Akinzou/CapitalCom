"""The documented examples are code: each one runs offline, and the README shows the real one."""

import re
import runpy
from collections.abc import Iterator
from pathlib import Path

import pytest
import responses

from capitalcom.application.ports import StreamTransport
from tests.fakes import FakeClock, FakeConnection, FakeStreamTransport, auto_ack, quote_frame
from tests.unit.docs.fake_demo import FakeDemo

ROOT = Path(__file__).parents[3]
EXAMPLES = sorted((ROOT / "docs" / "examples").glob("*.py"))
QUICKSTART = ROOT / "docs" / "examples" / "quickstart.py"
ERRORS = ROOT / "docs" / "examples" / "errors.py"


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch) -> Iterator[responses.RequestsMock]:
    for name in ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_PASSWORD"):
        monkeypatch.setenv(name, f"{name.lower()}-example-0001")
    connection = FakeConnection([quote_frame("BTCUSD")] * 5, auto_ack)

    def transport(_session: object) -> StreamTransport:
        return FakeStreamTransport(FakeClock(), [connection])

    monkeypatch.setattr("capitalcom.api.client.stream_transport", transport)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        FakeDemo(mock)
        yield mock


def test_examples_exist() -> None:
    names = {path.stem for path in EXAMPLES}
    assert {"quickstart", "sessions", "markets", "trading", "errors", "streaming"} <= names


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.stem)
def test_every_example_runs_against_the_fake_api(
    path: Path, demo: responses.RequestsMock, capsys: pytest.CaptureFixture[str]
) -> None:
    runpy.run_path(str(path), run_name="__main__")
    assert capsys.readouterr().out.strip(), f"{path.name} printed nothing"
    # Every session an example opens is closed again: it logs out on the way out.
    logins = [c for c in demo.calls if c.request.method == "POST" and _is_session(c.request.url)]
    logouts = [c for c in demo.calls if c.request.method == "DELETE" and _is_session(c.request.url)]
    assert len(logins) == len(logouts) >= 1


def test_quickstart_prints_no_identifiers(
    demo: responses.RequestsMock, capsys: pytest.CaptureFixture[str]
) -> None:
    # The contract job runs the quick start, and its output lands in a public CI log.
    runpy.run_path(str(QUICKSTART), run_name="__main__")
    out = capsys.readouterr().out
    assert "ACCEPTED" in out
    assert "SECRET" not in out


def test_errors_example_treats_an_unconfirmed_deal_as_possibly_open(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The reliability page's recipe: a confirmation that never came may still be a deal, so a
    # bot copying it must look before resending, never log "failed" and send again.
    for name in ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_PASSWORD"):
        monkeypatch.setenv(name, f"{name.lower()}-example-0001")
    monkeypatch.setattr("capitalcom.api.composition.SystemClock", FakeClock)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        FakeDemo(mock, confirms=False)
        runpy.run_path(str(ERRORS), run_name="__main__")
    out = capsys.readouterr().out
    assert "may exist" in out
    assert "failed" not in out


def test_readme_quickstart_is_the_example() -> None:
    # PyPI shows the README without includes, so the quick start is copied into it; this keeps
    # the copy identical to the file the tests run.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```python\n(.*?)```", readme, re.DOTALL)
    assert block is not None, "README has no python block"
    assert block.group(1) == QUICKSTART.read_text(encoding="utf-8")


def _is_session(url: str | None) -> bool:
    return (url or "").split("?")[0].endswith("/api/v1/session")
