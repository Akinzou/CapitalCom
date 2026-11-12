"""The README quick start, run unchanged against the demo server."""

import runpy
import time
from pathlib import Path

import pytest

from tests.contract.conftest import Market, smoke

QUICKSTART = Path(__file__).parents[2] / "docs" / "examples" / "quickstart.py"


@pytest.mark.contract
def test_quickstart_runs_on_demo(btc: Market, capsys: pytest.CaptureFixture[str]) -> None:
    # btc closes whatever the script leaves open, and skips a closed market (fails it in the
    # release smoke, see conftest.smoke). The script reads the same CAPITAL_* variables the
    # contract job sets, and logs in with its own client,
    # whose rate limiter cannot see the shared client's login: the server allows one session
    # creation per second (ADR 0006), so the second login waits that second out here.
    time.sleep(1.0)
    runpy.run_path(str(QUICKSTART), run_name="__main__")
    out = capsys.readouterr().out
    assert "open: ACCEPTED" in out
    if smoke():
        # A netted deal closes nothing, so it would pass the smoke without positions.close.
        assert "close: ACCEPTED" in out
    else:
        assert "close: ACCEPTED" in out or "netted" in out
