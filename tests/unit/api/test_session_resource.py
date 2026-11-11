"""``cc.session``: info, server time and account switch."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.errors import ApiError, ResponseFormatError
from tests.unit.api.test_facade import DEMO, TOKENS, calls

SESSION = {
    "clientId": "12345678",
    "accountId": "12345678901234567",
    "timezoneOffset": 3,
    "locale": "en",
    "currency": "USD",
    "streamEndpoint": "wss://api-streaming-capital.backend-capital.com/",
}


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(f"{DEMO}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        yield mock


def client() -> CapitalCom:
    return CapitalCom("res-key-0001", "me@example.com", "res-pw-0001")


def test_server_time_does_not_log_in(api: responses.RequestsMock) -> None:
    api.get(f"{DEMO}/api/v1/time", json={"serverTime": 1647440528194})
    assert client().session.server_time() == datetime(2022, 3, 16, 14, 22, 8, 194000, tzinfo=UTC)
    assert calls(api) == [("GET", "/api/v1/time")]
    assert "CST" not in api.calls[0].request.headers


def test_server_time_without_server_time_raises(api: responses.RequestsMock) -> None:
    api.get(f"{DEMO}/api/v1/time", json={"time": 1})
    with pytest.raises(ResponseFormatError, match="serverTime"):
        client().session.server_time()


def test_info_that_is_not_an_object_raises(api: responses.RequestsMock) -> None:
    api.get(f"{DEMO}/api/v1/session", json=[SESSION])
    with pytest.raises(ResponseFormatError, match="'session'"):
        client().session.info()


def test_info_parses_session(api: responses.RequestsMock) -> None:
    api.get(f"{DEMO}/api/v1/session", json=SESSION)
    info = client().session.info()
    assert info.client_id == "12345678"
    assert info.account_id == "12345678901234567"
    assert info.timezone_offset == Decimal(3)
    assert info.locale == "en"
    assert info.currency == "USD"
    assert info.stream_endpoint == "wss://api-streaming-capital.backend-capital.com/"
    assert info.raw == SESSION


def test_info_with_missing_account_id_raises_response_format_error(
    api: responses.RequestsMock,
) -> None:
    api.get(f"{DEMO}/api/v1/session", json={**SESSION, "accountId": None})
    with pytest.raises(ResponseFormatError, match="accountId"):
        client().session.info()


def test_switch_account_raises_typed_error_on_rejection(api: responses.RequestsMock) -> None:
    api.put(f"{DEMO}/api/v1/session", status=400, json={"errorCode": "error.invalid.accountId"})
    with pytest.raises(ApiError) as caught:
        client().session.switch_account("B")
    assert caught.value.error_code == "error.invalid.accountId"


def test_switch_account_sends_put(api: responses.RequestsMock) -> None:
    api.put(f"{DEMO}/api/v1/session", json={"trailingStopsEnabled": False})
    client().session.switch_account("B")
    assert calls(api) == [("POST", "/api/v1/session"), ("PUT", "/api/v1/session")]
