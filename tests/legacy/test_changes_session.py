"""Changed rows of the legacy session surface (spec §7 change 1 and 3; plan rulings 2, 7, 8,
10 and 11). Each test here failed against 1.0.4."""

import logging
import subprocess
import sys
import time
import warnings

import pytest
import responses

import capitalcom
import capitalcom.client
from capitalcom.client import CapitalClient, colored_log
from capitalcom.domain.errors import AuthenticationError, ValidationError
from capitalcom.legacy import deprecation
from tests.legacy.conftest import (
    API_KEY,
    DEMO,
    IDENTIFIER,
    LOGIN,
    PASSWORD,
    legacy,
    logins,
    sent,
)

ACCOUNTS = f"{DEMO}/api/v1/accounts"


def timeout_of(api: responses.RequestsMock) -> object:
    # responses records the keyword arguments requests was called with; the stubs omit it.
    return api.calls[-1].request.req_kwargs["timeout"]  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def fresh_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deprecation, "_warned", set())


def test_import_configures_no_logging() -> None:
    code = "import logging, capitalcom; print(len(logging.getLogger().handlers))"
    result = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "0"


def test_colored_log_has_no_ansi(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        colored_log("INFO", "plain text")
    assert [r.getMessage() for r in caplog.records] == ["plain text"]


def test_login_failure_is_authentication_error(
    api: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    api.replace(responses.POST, LOGIN, status=401, json={"errorCode": "error.invalid.details"})
    with caplog.at_level(logging.DEBUG), pytest.raises(AuthenticationError) as raised:
        legacy()
    for secret in (API_KEY, PASSWORD):
        assert secret not in str(raised.value)
        assert secret not in caplog.text


def test_constructor_and_methods_warn_once(api: responses.RequestsMock) -> None:
    with pytest.warns(DeprecationWarning, match=r"^CapitalClient is deprecated.*migration\.md"):
        client = legacy()
    with pytest.warns(DeprecationWarning, match=r"^CapitalClient\.lot_to_size is deprecated"):
        client.lot_to_size(1, 10)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        legacy().lot_to_size(1, 10)
    assert [w for w in caught if issubclass(w.category, DeprecationWarning)] == []


@pytest.mark.parametrize("override", [{"verify": False}, {"allow_redirects": True}])
def test_request_refuses_tls_and_redirect_overrides(
    api: responses.RequestsMock, override: dict[str, bool]
) -> None:
    client = legacy()
    with pytest.raises(ValidationError):
        client._request("GET", "/api/v1/accounts", **override)
    assert sent(api) == []


def test_request_has_a_timeout(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": []})
    client = legacy()
    client._request("GET", "/api/v1/accounts")
    assert timeout_of(api) == (5.0, 15.0)
    client._request("GET", "/api/v1/accounts", timeout=3)
    assert timeout_of(api) == 3


def test_credentials_are_read_only_and_masked(api: responses.RequestsMock) -> None:
    client = legacy()
    assert (client.api_key, client.login, client.password) == (API_KEY, IDENTIFIER, PASSWORD)
    for secret in (API_KEY, IDENTIFIER, PASSWORD):
        assert secret not in repr(client)
    for name in ("api_key", "login", "password", "session", "base_url"):
        with pytest.raises(AttributeError):
            setattr(client, name, "changed")


def test_token_attributes_round_trip_through_the_core(api: responses.RequestsMock) -> None:
    api.get(ACCOUNTS, json={"accounts": []})
    client = legacy()
    client.token_expiry = time.time() + 3600
    client._request("GET", "/api/v1/accounts")
    assert logins(api) == 1
    client.cst = None
    # As in 1.0.4, clearing one half leaves the other readable.
    assert client._headers() == {"CST": None, "X-SECURITY-TOKEN": "tok-1"}
    client._request("GET", "/api/v1/accounts")
    assert logins(api) == 2


def test_all_lists_the_legacy_names() -> None:
    assert sorted(capitalcom.client.__all__) == [
        "BLUE",
        "CapitalClient",
        "GREEN",
        "RED",
        "RESET",
        "colored_log",
    ]
    assert "random" not in vars(capitalcom)
    assert CapitalClient.__module__ == "capitalcom.client"
