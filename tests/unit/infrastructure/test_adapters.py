from datetime import UTC
from decimal import Decimal
from typing import Any

import pytest
import requests
import responses

from capitalcom.application.ports import HttpRequest
from capitalcom.application.result import Err, Ok
from capitalcom.infrastructure.requests_transport import RequestsTransport
from capitalcom.infrastructure.system_clock import SystemClock

BASE = "https://demo.example"


@responses.activate
def test_success_maps_to_http_response() -> None:
    responses.get(f"{BASE}/api/v1/ping", json={"status": "OK"}, headers={"CST": "t"})
    result = RequestsTransport(BASE).send(HttpRequest("GET", "/api/v1/ping"))
    assert isinstance(result, Ok)
    assert result.value.status == 200
    assert result.value.header("cst") == "t"
    assert result.value.json() == {"status": "OK"}


@responses.activate
def test_decimal_body_is_sent_as_json_number() -> None:
    responses.post(f"{BASE}/api/v1/positions", json={})
    RequestsTransport(BASE).send(
        HttpRequest("POST", "/api/v1/positions", json={"size": Decimal("0.001")})
    )
    sent = responses.calls[0].request
    assert sent.body == b'{"size": 0.001}'
    assert sent.headers["Content-Type"] == "application/json"


@responses.activate
def test_query_params_and_headers_are_sent() -> None:
    responses.get(f"{BASE}/api/v1/history", json={})
    RequestsTransport(BASE).send(HttpRequest("GET", "/api/v1/history", {"CST": "c"}, {"max": "10"}))
    sent = responses.calls[0].request
    assert sent.url == f"{BASE}/api/v1/history?max=10"
    assert sent.headers["CST"] == "c"


@responses.activate
def test_connect_timeout_never_reached_server() -> None:
    responses.get(f"{BASE}/api/v1/ping", body=requests.exceptions.ConnectTimeout("boom"))
    result = RequestsTransport(BASE).send(HttpRequest("GET", "/api/v1/ping"))
    assert isinstance(result, Err)
    assert result.error.reached_server is False


@responses.activate
def test_ssl_error_may_have_reached_server() -> None:
    # requests raises SSLError both for a failed handshake and for TLS dropped while the
    # response was read; only the first is "never sent", and the two cannot be told apart.
    responses.post(f"{BASE}/api/v1/positions", body=requests.exceptions.SSLError("eof"))
    result = RequestsTransport(BASE).send(HttpRequest("POST", "/api/v1/positions"))
    assert isinstance(result, Err)
    assert result.error.reached_server is True


@responses.activate
def test_read_timeout_may_have_reached_server_and_names_only_the_call() -> None:
    responses.post(
        f"{BASE}/api/v1/positions", body=requests.exceptions.ReadTimeout("secret-ish detail")
    )
    result = RequestsTransport(BASE).send(HttpRequest("POST", "/api/v1/positions"))
    assert isinstance(result, Err)
    assert result.error.reached_server is True
    assert "POST /api/v1/positions" in str(result.error)
    assert "secret-ish" not in str(result.error)


@responses.activate
def test_redirect_is_returned_not_followed() -> None:
    responses.get(f"{BASE}/api/v1/ping", status=302, headers={"Location": "https://evil.example/x"})
    responses.get("https://evil.example/x", json={})
    result = RequestsTransport(BASE).send(HttpRequest("GET", "/api/v1/ping", {"CST": "c"}))
    assert isinstance(result, Ok)
    assert result.value.status == 302
    assert len(responses.calls) == 1


@pytest.mark.parametrize("url", ["http://x", "ftp://x", "x"])
def test_plain_http_base_url_is_refused(url: str) -> None:
    with pytest.raises(ValueError, match="https"):
        RequestsTransport(url)


class RecordingSession(requests.Session):
    """A caller-supplied session configured insecurely; records what the transport passes."""

    def __init__(self) -> None:
        super().__init__()
        self.verify = False
        self.calls: list[dict[str, Any]] = []

    def request(self, *args: Any, **kwargs: Any) -> requests.Response:
        self.calls.append(kwargs)
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        return response


def test_injected_session_cannot_disable_tls_or_enable_redirects() -> None:
    session = RecordingSession()
    RequestsTransport(BASE, session).send(HttpRequest("GET", "/api/v1/ping"))
    (kwargs,) = session.calls
    assert kwargs["verify"] is True
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (5.0, 15.0)


def test_system_clock() -> None:
    clock = SystemClock()
    first = clock.monotonic()
    clock.sleep(0)
    assert clock.monotonic() >= first
    assert clock.now_utc().tzinfo is UTC


class ClosableSession(requests.Session):
    closed = False

    def close(self) -> None:
        self.closed = True
        super().close()


def test_close_leaves_a_caller_supplied_session_open() -> None:
    session = ClosableSession()
    RequestsTransport(BASE, session).close()
    assert session.closed is False
