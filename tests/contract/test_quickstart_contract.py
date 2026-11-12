"""The README quick start, run unchanged against the demo server."""

import runpy
import time
from pathlib import Path

import pytest

from tests.contract.conftest import Market

QUICKSTART = Path(__file__).parents[2] / "docs" / "examples" / "quickstart.py"


@pytest.mark.contract
def test_quickstart_runs_on_demo(btc: Market, capsys: pytest.CaptureFixture[str]) -> None:
    # btc skips a closed market and closes whatever the script leaves open. The script reads
    # the same CAPITAL_* variables the contract job sets, and logs in with its own client,
    # whose rate limiter cannot see the shared client's login: the server allows one session
    # creation per second (ADR 0006), so the second login waits that second out here.
    time.sleep(1.0)
    runpy.run_path(str(QUICKSTART), run_name="__main__")
    out = capsys.readouterr().out
    assert "open: ACCEPTED" in out
    assert "close: ACCEPTED" in out or "netted" in out
