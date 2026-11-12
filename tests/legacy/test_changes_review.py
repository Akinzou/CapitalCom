"""Legacy behaviour fixed after the stage 3 reviews: warning location, CA bundles, read-only
network errors, paths off the host, restored token pairs, refused tokens and the clock."""

import os
import random
import time
import warnings
from datetime import UTC, datetime
from unittest import mock

import pytest
import requests
import responses

import capitalcom.client
from capitalcom.client import CapitalClient
from capitalcom.domain.errors import ValidationError
from capitalcom.infrastructure.system_clock import SystemClock
from capitalcom.legacy import deprecation
from tests.legacy.conftest import API_KEY, DEMO, IDENTIFIER, PASSWORD, legacy, logins, sent
from tests.legacy.golden.payloads import account

ACCOUNTS = f"{DEMO}/api/v1/accounts"


def test_warnings_point_at_the_callers_line(
    api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deprecation, "_warned", set())
    api.get(ACCOUNTS, json={"accounts": [account("A", 1.5)]})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        client = CapitalClient(API_KEY, IDENTIFIER, PASSWORD)
        client.get_balance()
    files = {os.path.normcase(w.filename) for w in caught}
    assert files == {os.path.normcase(__file__)}


def test_session_ca_bundle_is_kept(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": [account("A", 1.5)]})
    client = legacy()
    client.session.verify = "/etc/corp-ca.pem"
    client.get_balance()
    assert api.calls[-1].request.req_kwargs["verify"] == "/etc/corp-ca.pem"  # type: ignore[attr-defined]
    client._request("GET", "/api/v1/accounts", verify="/etc/other-ca.pem")
    assert api.calls[-1].request.req_kwargs["verify"] == "/etc/other-ca.pem"  # type: ignore[attr-defined]
    client._request("GET", "/api/v1/accounts", verify=True, allow_redirects=False)


def test_lookup_network_errors_stay_requests_errors(api: responses.RequestsMock) -> None:
    api.get(f"{DEMO}/api/v1/confirms/o_1", body=requests.exceptions.ConnectionError("down"))
    client = legacy()
    with pytest.raises(requests.exceptions.ConnectionError):
        client.get_deal_by_ref("o_1")


@pytest.mark.parametrize("path", ["@evil.example/x", "api/v1/accounts", ""])
def test_request_refuses_paths_off_the_host(api: responses.RequestsMock, path: str) -> None:
    client = legacy()
    with pytest.raises(ValidationError, match="path"):
        client._request("GET", path)
    assert sent(api) == []


def test_restored_tokens_survive_a_dropped_session(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": []})
    client = legacy()
    client.cst = None
    client.cst = "cst-saved"
    assert client.cst == "cst-saved"
    client.security_token = "tok-saved"  # noqa: S105 - fake token
    client._request("GET", "/api/v1/accounts")
    headers = api.calls[-1].request.headers
    assert (headers["CST"], headers["X-SECURITY-TOKEN"]) == ("cst-saved", "tok-saved")
    assert logins(api) == 1


def test_module_still_exposes_time_and_random() -> None:
    # 1.0.4 test suites patch "capitalcom.client.time.sleep" to skip the waits.
    with mock.patch("capitalcom.client.time.sleep") as sleep:
        time.sleep(5)
    sleep.assert_called_once_with(5)
    assert capitalcom.client.random is random
    assert {"time", "random"}.isdisjoint(capitalcom.client.__all__)


def test_a_second_401_drops_the_refused_tokens(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, status=401)
    client = legacy()
    assert client._request("GET", "/api/v1/accounts").status_code == 401
    assert client.cst is None
    assert logins(api) == 2


def test_token_expiry_reads_the_core_clock(
    api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = datetime(2001, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(SystemClock, "now_utc", lambda self: fixed)
    api.get(ACCOUNTS, json={"accounts": []})
    client = legacy()
    client._request("GET", "/api/v1/accounts")
    assert abs(client.token_expiry - (fixed.timestamp() + 600)) < 5
    # In the clock's future, though long past by the wall clock: the session stays.
    client.token_expiry = fixed.timestamp() + 60
    client._request("GET", "/api/v1/accounts")
    assert logins(api) == 1
