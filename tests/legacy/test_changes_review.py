"""Legacy behaviour fixed after the stage 3 reviews: warning location, CA bundles, read-only
network errors, paths off the host and restored token pairs."""

import os
import warnings

import pytest
import requests
import responses

from capitalcom.client import CapitalClient
from capitalcom.domain.errors import ValidationError
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
