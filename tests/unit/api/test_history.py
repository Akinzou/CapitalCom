"""``cc.history``."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.errors import ValidationError
from tests.unit.api.test_facade import DEMO, TOKENS, calls
from tests.unit.domain.test_history import ACTIVITY, TRANSACTION


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(f"{DEMO}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        mock.get(f"{DEMO}/api/v1/history/activity", json={"activities": [ACTIVITY]})
        mock.get(f"{DEMO}/api/v1/history/transactions", json={"transactions": [TRANSACTION]})
        yield mock


def client() -> CapitalCom:
    return CapitalCom("his-key-0001", "me@example.com", "his-pw-0001")


def query(mock: responses.RequestsMock) -> dict[str, list[str]]:
    url = mock.calls[-1].request.url
    assert isinstance(url, str)
    return parse_qs(urlsplit(url).query)


def test_activity_sends_utc_range(api: responses.RequestsMock) -> None:
    start = datetime(2022, 4, 1, 3, 1, tzinfo=timezone(timedelta(hours=2)))
    (activity,) = client().history.activity(start=start, end=start + timedelta(hours=1))
    assert activity.status == "ACCEPTED"
    assert query(api) == {"from": ["2022-04-01T01:01:00"], "to": ["2022-04-01T02:01:00"]}


def test_activity_sends_optional_filters(api: responses.RequestsMock) -> None:
    client().history.activity(
        last_period=timedelta(minutes=5), detailed=True, deal_id="d1", fiql="epic==SILVER"
    )
    assert query(api) == {
        "lastPeriod": ["300"],
        "detailed": ["true"],
        "dealId": ["d1"],
        "filter": ["epic==SILVER"],
    }


def test_activity_over_one_day_sends_nothing(api: responses.RequestsMock) -> None:
    start = datetime(2022, 4, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        client().history.activity(start=start, end=start + timedelta(days=2))
    assert calls(api) == []


def test_naive_start_sends_nothing(api: responses.RequestsMock) -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        client().history.transactions(start=datetime(2022, 4, 1))  # noqa: DTZ001
    assert calls(api) == []


def test_transactions_send_type_and_allow_long_range(api: responses.RequestsMock) -> None:
    start = datetime(2022, 4, 1, tzinfo=UTC)
    cc = client()
    (transaction,) = cc.history.transactions(
        start=start, end=start + timedelta(days=30), transaction_type="TRADE"
    )
    assert transaction.reference == "ABC123"
    assert query(api)["type"] == ["TRADE"]


def test_transactions_by_last_period(api: responses.RequestsMock) -> None:
    client().history.transactions(last_period=timedelta(days=3))
    assert query(api) == {"lastPeriod": ["259200"]}
