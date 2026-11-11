"""``cc.prices``."""

from collections.abc import Iterator

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import NotFoundError, ValidationError
from tests.unit.api.test_facade import DEMO, TOKENS
from tests.unit.domain.test_prices import FIRST_BAR
from tests.unit.market_payloads import wire

PRICES = f"{DEMO}/api/v1/prices"


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(f"{DEMO}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        yield mock


def client() -> CapitalCom:
    return CapitalCom("prc-key-0001", "me@example.com", "prc-pw-0001")


def test_history_sends_resolution_and_limit(api: responses.RequestsMock) -> None:
    api.get(f"{PRICES}/BTCUSD", json=wire({"prices": [FIRST_BAR] * 3, "instrumentType": "X"}))
    bars = client().prices.history("BTCUSD", Resolution.MINUTE, limit=3)
    assert len(bars) == 3
    assert api.calls[-1].request.url == f"{PRICES}/BTCUSD?resolution=MINUTE&max=3"


def test_an_empty_window_is_an_empty_answer(api: responses.RequestsMock) -> None:
    api.get(f"{PRICES}/BTCUSD", status=404, json={"errorCode": "error.prices.not-found"})
    assert client().prices.history("BTCUSD") == ()


def test_an_unknown_epic_still_raises(api: responses.RequestsMock) -> None:
    api.get(f"{PRICES}/NOSUCH", status=404, json={"errorCode": "error.not-found.epic"})
    with pytest.raises(NotFoundError):
        client().prices.history("NOSUCH")


def test_history_encodes_the_epic_and_refuses_a_blank_one(api: responses.RequestsMock) -> None:
    api.get(f"{PRICES}/A%2FB", json={"prices": []})
    assert client().prices.history("A/B") == ()
    with pytest.raises(ValidationError):
        client().prices.history(" ")
    assert len(api.calls) == 2
