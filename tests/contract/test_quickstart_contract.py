"""The README quick start, run unchanged against the demo server."""

import runpy
from pathlib import Path

import pytest

from tests.contract.conftest import Market

QUICKSTART = Path(__file__).parents[2] / "docs" / "examples" / "quickstart.py"


@pytest.mark.contract
def test_quickstart_runs_on_demo(btc: Market, capsys: pytest.CaptureFixture[str]) -> None:
    # btc skips a closed market and closes whatever the script leaves open. The script reads
    # the same CAPITAL_* variables the contract job sets, and logs in with its own client.
    runpy.run_path(str(QUICKSTART), run_name="__main__")
    out = capsys.readouterr().out
    assert "open: ACCEPTED" in out
    assert "close: ACCEPTED" in out or "netted" in out
