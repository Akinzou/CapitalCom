"""Changed rows of legacy trading (spec §7 changes 2, 4 and 5; ADR 0007; plan rulings 4, 5
and 9). Each test here failed against 1.0.4."""

import logging

import pytest
import requests
import responses

from capitalcom.client import CapitalClient
from capitalcom.domain.errors import (
    CapitalComError,
    DealRejectedError,
    OutcomeUnknownError,
    ValidationError,
)
from capitalcom.legacy import deprecation
from tests.legacy.conftest import API_KEY, DEMO, IDENTIFIER, PASSWORD, legacy, sent
from tests.legacy.golden.payloads import confirm

POSITIONS = f"{DEMO}/api/v1/positions"
OPEN_CONFIRM = f"{DEMO}/api/v1/confirms/o_1"
CLOSE_CONFIRM = f"{DEMO}/api/v1/confirms/o_2"


def closable(api: responses.RequestsMock, status: str = "ACCEPTED") -> None:
    api.delete(f"{POSITIONS}/P1", json={"dealReference": "o_2"})
    api.get(CLOSE_CONFIRM, json=confirm("o_2", status=status, affected=(("P1", "FULLY_CLOSED"),)))


def opened(api: responses.RequestsMock, **answer: object) -> None:
    api.post(POSITIONS, json={"dealReference": "o_1"})
    api.get(OPEN_CONFIRM, json=confirm(**answer))  # type: ignore[arg-type]


def test_full_close_uses_the_documented_endpoint_and_confirms(
    api: responses.RequestsMock,
) -> None:
    closable(api)
    assert legacy().close_position_by_id("P1") == "SUCCESS"
    assert [(m, u) for m, u, _ in sent(api)] == [
        ("DELETE", f"{POSITIONS}/P1"),
        ("GET", CLOSE_CONFIRM),
    ]


def test_rejected_close_raises(api: responses.RequestsMock) -> None:
    closable(api, status="REJECTED")
    with pytest.raises(DealRejectedError):
        legacy().close_position_by_id("P1")


def test_partial_close_is_refused_before_sending(api: responses.RequestsMock) -> None:
    client = legacy()
    with pytest.raises(ValidationError, match="whole position"):
        client.close_position_by_id("P1", size=0.5)
    assert sent(api) == []
    closable(api)
    assert client.close_position_by_id("P1", size=0) == "SUCCESS"


def test_rejected_open_raises_deal_rejected(api: responses.RequestsMock) -> None:
    opened(api, status="REJECTED", affected=())
    with pytest.raises(DealRejectedError, match="RC_NOT_ENOUGH_MARGIN"):
        legacy().open_raw_position("BTCUSD", 50, "BUY")


def test_open_write_timeout_is_outcome_unknown(api: responses.RequestsMock) -> None:
    api.post(POSITIONS, body=requests.exceptions.ReadTimeout("slow"))
    with pytest.raises(OutcomeUnknownError):
        legacy().open_raw_position("BTCUSD", 0.0001, "BUY")
    assert [m for m, _, _ in sent(api)] == ["POST"]


def test_netting_open_says_no_position_opened(api: responses.RequestsMock) -> None:
    opened(api, affected=())
    with pytest.raises(CapitalComError, match="opened no position"):
        legacy().open_raw_position("BTCUSD", 0.0001, "SELL")


def test_rounded_open_returns_the_id_and_warns(
    api: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    opened(api, size=0.0001)
    with caplog.at_level(logging.WARNING):
        assert legacy().open_raw_position("BTCUSD", 0.00015, "BUY") == "P1"
    warning = next(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert "0.00015" in warning
    assert "0.0001" in warning


def test_trade_closes_by_id(api: responses.RequestsMock) -> None:
    opened(api)
    closable(api)
    legacy().test_trade()
    urls = [u for _, u, _ in sent(api)]
    assert f"{POSITIONS}/P1" in urls
    assert f"{DEMO}/api/v1/confirms/P1" not in urls


def test_forex_warning_names_jpy(
    api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened(api)
    client = legacy()
    monkeypatch.setattr(deprecation, "_warned", set())
    with pytest.warns(DeprecationWarning, match="JPY"):
        client.open_forex_position("EURUSD", 0.01, "BUY")


def test_close_by_ref_resolves_then_closes(api: responses.RequestsMock) -> None:
    api.get(OPEN_CONFIRM, json=confirm())
    closable(api)
    assert legacy().close_position_by_ref("o_1") == "SUCCESS"
    assert [u for _, u, _ in sent(api)] == [OPEN_CONFIRM, f"{POSITIONS}/P1", CLOSE_CONFIRM]


class Guarded(CapitalClient):
    """A 1.x subclass that guards opens and fixes the pip scale, as user code might."""

    def __init__(self) -> None:
        super().__init__(API_KEY, IDENTIFIER, PASSWORD)
        self.opens: list[tuple[str, float]] = []
        self.closes: list[str] = []

    def open_raw_position(
        self,
        epic: str,
        size: float,
        direction: str,
        stop_dist: float | None = None,
        profit_dist: float | None = None,
    ) -> str:
        self.opens.append((epic, size))
        return super().open_raw_position(epic, size, direction, stop_dist, profit_dist)

    def pips_to_profit_distance(self, pips: float | None, pip_position: int) -> float | None:
        return super().pips_to_profit_distance(pips, 3)

    def close_position_by_id(self, deal_id: str, size: float | None = None) -> str:
        self.closes.append(deal_id)
        return super().close_position_by_id(deal_id, size)


def test_subclass_overrides_are_still_called(api: responses.RequestsMock) -> None:
    opened(api)
    closable(api)
    client = Guarded()
    client.open_forex_position("USDJPY", 0.01, "BUY", stop_dist=100)
    assert client.opens == [("USDJPY", 0.01 * 100000)]
    post = next(body for method, _, body in sent(api) if method == "POST")
    assert post["stopDistance"] == 100 * 10**-3
    client.close_position_by_ref("o_1")
    assert client.closes == ["P1"]


def test_trade_goes_through_overridable_methods(api: responses.RequestsMock) -> None:
    opened(api)
    closable(api)
    client = Guarded()
    client.test_trade()
    assert client.opens == [("EURUSD", 0.001 * 100000)]
    assert client.closes == ["P1"]
