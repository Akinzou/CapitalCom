"""``cc.sentiment``."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.errors import ResponseFormatError, ValidationError
from tests.unit.api.test_facade import DEMO, TOKENS

SENTIMENT = f"{DEMO}/api/v1/clientsentiment"


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(f"{DEMO}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        yield mock


def client() -> CapitalCom:
    return CapitalCom("snt-key-0001", "me@example.com", "snt-pw-0001")


def test_get_reads_one_market(api: responses.RequestsMock) -> None:
    api.get(
        f"{SENTIMENT}/BTCUSD",
        json={
            "marketId": "BTCUSD",
            "longPositionPercentage": 86.58,
            "shortPositionPercentage": 13.42,
        },
    )
    sentiment = client().sentiment.get("BTCUSD")
    assert sentiment.market_id == "BTCUSD"
    assert sentiment.long_percentage == Decimal("86.58")
    assert sentiment.short_percentage == Decimal("13.42")


def test_get_many_keys_markets_in_answer_order(api: responses.RequestsMock) -> None:
    api.get(
        SENTIMENT,
        json={
            "clientSentiments": [
                {
                    "marketId": "SILVER",
                    "longPositionPercentage": 91.85,
                    "shortPositionPercentage": 8.15,
                },
                {
                    "marketId": "NATURALGAS",
                    "longPositionPercentage": 62.97,
                    "shortPositionPercentage": 37.03,
                },
            ]
        },
    )
    found = client().sentiment.get_many(["SILVER", "NATURALGAS"])
    assert list(found) == ["SILVER", "NATURALGAS"]
    assert found["NATURALGAS"].short_percentage == Decimal("37.03")
    assert api.calls[-1].request.url == f"{SENTIMENT}?marketIds=SILVER%2CNATURALGAS"


def test_a_row_without_percentages_is_refused(api: responses.RequestsMock) -> None:
    api.get(f"{SENTIMENT}/BTCUSD", json={"marketId": "BTCUSD", "longPositionPercentage": 1})
    with pytest.raises(ResponseFormatError, match="shortPositionPercentage"):
        client().sentiment.get("BTCUSD")


@pytest.mark.parametrize("ids", [[], "SILVER", [""]])
def test_get_many_refuses_bad_id_lists(api: responses.RequestsMock, ids: object) -> None:
    with pytest.raises(ValidationError, match="market_ids"):
        client().sentiment.get_many(ids)  # type: ignore[arg-type]
    assert len(api.calls) == 0


@pytest.mark.parametrize("market_id", ["", "..", None])
def test_get_refuses_a_bad_id(api: responses.RequestsMock, market_id: object) -> None:
    with pytest.raises(ValidationError, match="market_id"):
        client().sentiment.get(market_id)  # type: ignore[arg-type]
    assert len(api.calls) == 0
