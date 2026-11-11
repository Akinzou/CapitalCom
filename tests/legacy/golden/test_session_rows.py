"""Golden rows: construction, session attributes, ``_request`` and ``colored_log``."""

import json
import logging
import time

import pytest
import requests
import responses

from capitalcom.client import colored_log
from tests.legacy.golden.conftest import (
    API_KEY,
    DEMO,
    IDENTIFIER,
    LIVE,
    LOGIN,
    PASSWORD,
    legacy,
    logins,
)

ACCOUNTS = f"{DEMO}/api/v1/accounts"


def test_constructor_logs_in_eagerly(api: responses.RequestsMock) -> None:
    legacy()
    assert logins(api) == 1
    login = api.calls[0].request
    assert login.headers["X-CAP-API-KEY"] == API_KEY
    assert json.loads(login.body or "") == {"identifier": IDENTIFIER, "password": PASSWORD}


def test_login_failure_raises(api: responses.RequestsMock) -> None:
    api.replace(responses.POST, LOGIN, status=401, json={"errorCode": "error.invalid.details"})
    with pytest.raises(Exception):  # noqa: B017, PT011 - 1.0.4 raised a bare Exception
        legacy()


def test_attributes_mirror_the_session(api: responses.RequestsMock) -> None:
    client = legacy()
    assert (client.cst, client.security_token) == ("cst-1", "tok-1")
    assert client.base_url == DEMO
    assert isinstance(client.session, requests.Session)
    assert abs(client.token_expiry - (time.time() + 600)) < 5
    assert client._headers() == {"CST": "cst-1", "X-SECURITY-TOKEN": "tok-1"}


def test_live_flag_selects_the_live_host() -> None:
    with responses.RequestsMock() as mock:
        mock.post(f"{LIVE}/api/v1/session", json={}, headers={"CST": "c", "X-SECURITY-TOKEN": "t"})
        assert legacy(demo=False).base_url == LIVE


def test_assigned_tokens_are_sent(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": []})
    client = legacy()
    client.cst = "cst-x"
    client.security_token = "tok-x"  # noqa: S105 - fake token
    client._request("GET", "/api/v1/accounts")
    headers = api.calls[-1].request.headers
    assert (headers["CST"], headers["X-SECURITY-TOKEN"]) == ("cst-x", "tok-x")


def test_past_token_expiry_forces_a_login(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": []})
    client = legacy()
    client.token_expiry = 0
    client._request("GET", "/api/v1/accounts")
    assert logins(api) == 2


def test_request_returns_the_raw_response_for_any_status(api: responses.RequestsMock) -> None:
    api.get(f"{DEMO}/api/v1/positions/X", status=404, json={"errorCode": "error.not-found.dealId"})
    response = legacy()._request("GET", "/api/v1/positions/X")
    assert isinstance(response, requests.Response)
    assert response.status_code == 404
    assert response.json() == {"errorCode": "error.not-found.dealId"}


def test_request_logs_in_again_once_on_401(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, status=401, json={"errorCode": "error.invalid.session.token"})
    api.get(ACCOUNTS, json={"accounts": []})
    response = legacy()._request("GET", "/api/v1/accounts")
    assert response.status_code == 200
    assert logins(api) == 2


def test_request_waits_on_429(api: responses.RequestsMock, slept: list[float]) -> None:
    api.get(ACCOUNTS, status=429, json={"errorCode": "error.too-many.requests"})
    api.get(ACCOUNTS, json={"accounts": []})
    assert legacy()._request("GET", "/api/v1/accounts").status_code == 200
    assert 1.0 in slept


def test_request_passes_params_and_json(api: responses.RequestsMock) -> None:
    api.post(f"{DEMO}/api/v1/thing", json={})
    legacy()._request("POST", "/api/v1/thing", params={"a": "b"}, json={"k": 1})
    request = api.calls[-1].request
    assert (request.url or "").endswith("/api/v1/thing?a=b")
    assert json.loads(request.body or "") == {"k": 1}


def test_login_session_renews_tokens(api: responses.RequestsMock) -> None:
    client = legacy()
    api.replace(responses.POST, LOGIN, json={}, headers={"CST": "cst-2", "X-SECURITY-TOKEN": "t2"})
    client.login_session()
    assert (client.cst, client.security_token) == ("cst-2", "t2")


def test_session_settings_reach_requests(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": []})
    client = legacy()
    client.session.headers["X-Trace"] = "abc"
    client._request("GET", "/api/v1/accounts")
    assert api.calls[-1].request.headers["X-Trace"] == "abc"


def test_colored_log_logs_the_text_at_its_level(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        colored_log("WARNING", "golden text")
    record = next(r for r in caplog.records if "golden text" in r.getMessage())
    assert record.levelname == "WARNING"
