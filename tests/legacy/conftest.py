"""Fixtures of the legacy tests and of the golden suite, which replays the 1.0.4 contract
against recorded HTTP shapes.

The suite was first run against the untouched 1.0.4 module, so a passing test here describes
what 1.0.4 really did, not what we believed it did.
"""

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
import responses

from capitalcom.client import CapitalClient

DEMO = "https://demo-api-capital.backend-capital.com"
LIVE = "https://api-capital.backend-capital.com"
LOGIN = f"{DEMO}/api/v1/session"
TOKENS = {"CST": "cst-1", "X-SECURITY-TOKEN": "tok-1"}
API_KEY = "gold-key-0001"
IDENTIFIER = "me@example.com"
PASSWORD = "gold-pw-0001"  # noqa: S105 - fake, never a real credential


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(LOGIN, json={"currentAccountId": "A"}, headers=TOKENS)
        yield mock


@pytest.fixture(autouse=True)
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Every ``time.sleep`` the client makes, recorded instead of slept."""
    calls: list[float] = []
    monkeypatch.setattr(time, "sleep", calls.append)
    return calls


def legacy(demo: bool = True) -> CapitalClient:
    return CapitalClient(API_KEY, IDENTIFIER, PASSWORD, demo=demo)


def sent(mock: responses.RequestsMock) -> list[tuple[str, str, Any]]:
    """Method, URL and JSON body of each request after the logins."""
    return [
        (call.request.method or "", call.request.url or "", _body(call.request.body))
        for call in mock.calls
        if not (call.request.url or "").endswith("/api/v1/session")
    ]


def logins(mock: responses.RequestsMock) -> int:
    return sum(
        1
        for call in mock.calls
        if call.request.method == "POST" and (call.request.url or "").endswith("/session")
    )


def _body(body: object) -> Any:
    if body is None:
        return None
    return json.loads(body.decode() if isinstance(body, bytes) else str(body))
