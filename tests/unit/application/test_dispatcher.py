import logging
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.error_mapping import error_for, outcome_unknown
from capitalcom.application.ports import HttpRequest, HttpResponse
from capitalcom.application.rate_limiter import RateLimiter, RequestKind, SlidingWindow
from capitalcom.application.result import Err, Ok
from capitalcom.application.retry import RetryPolicy
from capitalcom.domain.errors import (
    ApiError,
    AuthenticationError,
    NotFoundError,
    OutcomeUnknownError,
    RateLimitError,
    TransportError,
    ValidationError,
)
from tests.fakes import EPOCH, FakeClock, FakeTransport, response

GET = HttpRequest("GET", "/api/v1/accounts")
POST = HttpRequest("POST", "/api/v1/positions")


def make(
    script: list[HttpResponse | TransportError],
) -> tuple[Dispatcher, FakeTransport, FakeClock]:
    clock = FakeClock()
    transport = FakeTransport(script)
    dispatcher = Dispatcher(transport, clock, RateLimiter(clock), RetryPolicy(), rand=lambda: 0.0)
    return dispatcher, transport, clock


def test_success_is_ok() -> None:
    dispatcher, _, _ = make([response(200, b"{}")])
    assert isinstance(dispatcher.send(GET), Ok)


def test_429_with_retry_after_then_success() -> None:
    dispatcher, transport, clock = make(
        [response(429, headers={"Retry-After": "2"}), response(200, b"{}")]
    )
    assert isinstance(dispatcher.send(POST), Ok)
    assert 2.0 in clock.sleeps
    assert len(transport.requests) == 2


def test_429_exhausted_is_rate_limit_error() -> None:
    dispatcher, transport, _ = make([response(429, headers={"Retry-After": "1"})])
    result = dispatcher.send(GET)
    assert isinstance(result, Err)
    assert isinstance(result.error, RateLimitError)
    assert result.error.retry_after == 1.0
    assert len(transport.requests) == 3


def test_post_timeout_after_sending_is_outcome_unknown_and_not_retried() -> None:
    timeout = TransportError("read timeout", reached_server=True)
    dispatcher, transport, _ = make([timeout])
    result = dispatcher.send(POST)
    assert isinstance(result, Err)
    assert isinstance(result.error, OutcomeUnknownError)
    assert result.error.__cause__ is timeout
    assert len(transport.requests) == 1


def test_post_connect_error_is_transport_error_and_not_retried() -> None:
    dispatcher, transport, _ = make([TransportError("refused", reached_server=False)])
    result = dispatcher.send(POST)
    assert isinstance(result, Err)
    assert type(result.error) is TransportError
    assert len(transport.requests) == 1


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_post_5xx_is_outcome_unknown_and_not_retried(status: int) -> None:
    dispatcher, transport, _ = make([response(status)])
    result = dispatcher.send(POST)
    assert isinstance(result, Err)
    assert isinstance(result.error, OutcomeUnknownError)
    assert isinstance(result.error.__cause__, ApiError)
    assert result.error.__cause__.status == status
    assert len(transport.requests) == 1


def test_get_transport_error_then_success_is_retried() -> None:
    dispatcher, transport, clock = make([TransportError("reset"), response(200, b"{}")])
    assert isinstance(dispatcher.send(GET), Ok)
    assert len(transport.requests) == 2
    assert clock.sleeps == [pytest.approx(0.25)]


def test_get_transport_error_exhausted_returns_last_transport_error() -> None:
    dispatcher, transport, _ = make([TransportError("reset")])
    result = dispatcher.send(GET)
    assert isinstance(result, Err)
    assert type(result.error) is TransportError
    assert len(transport.requests) == 3


def test_get_502_html_exhausted_is_api_error_without_code() -> None:
    dispatcher, transport, _ = make([response(502, b"<html>" + b"x" * 2000)])
    result = dispatcher.send(GET)
    assert isinstance(result, Err)
    assert type(result.error) is ApiError
    assert result.error.status == 502
    assert result.error.error_code is None
    assert len(result.error.body) <= 500
    assert len(transport.requests) == 3


def test_get_500_is_not_retried() -> None:
    dispatcher, transport, _ = make([response(500, b'{"errorCode":"error.internal"}')])
    result = dispatcher.send(GET)
    assert isinstance(result, Err)
    assert len(transport.requests) == 1


def test_401_maps_to_authentication_error_without_retry() -> None:
    dispatcher, transport, _ = make([response(401, b'{"errorCode":"error.invalid.api.key"}')])
    result = dispatcher.send(GET)
    assert isinstance(result, Err)
    assert isinstance(result.error, AuthenticationError)
    assert result.error.error_code == "error.invalid.api.key"
    assert len(transport.requests) == 1


def test_error_for_maps_statuses() -> None:
    assert type(error_for(response(404, b"{}"), EPOCH)) is NotFoundError
    assert type(error_for(response(400, b'{"errorCode":"x"}'), EPOCH)) is ApiError
    limited = error_for(response(429, headers={"retry-after": "5"}), EPOCH)
    assert isinstance(limited, RateLimitError)
    assert limited.retry_after == 5.0


@pytest.mark.parametrize("body", [b"", b"[1]", b'{"errorCode": 7}', b"\xff\xfe"])
def test_error_for_tolerates_odd_bodies(body: bytes) -> None:
    error = error_for(response(400, body), EPOCH)
    assert error.error_code is None


def test_retry_after_over_a_minute_is_returned_at_once() -> None:
    dispatcher, transport, clock = make([response(429, headers={"Retry-After": "3600"})])
    result = dispatcher.send(GET)
    assert isinstance(result, Err)
    assert isinstance(result.error, RateLimitError)
    assert result.error.retry_after == 3600.0
    assert clock.sleeps == []
    assert len(transport.requests) == 1


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_session_requests_are_retried_on_gateway_errors(method: str) -> None:
    dispatcher, transport, _ = make([response(503), response(200, b"{}")])
    assert isinstance(dispatcher.send(HttpRequest(method, "/api/v1/session")), Ok)
    assert len(transport.requests) == 2


def test_session_request_transport_error_is_retried() -> None:
    dispatcher, transport, _ = make([TransportError("reset"), response(200, b"{}")])
    assert isinstance(dispatcher.send(HttpRequest("POST", "/api/v1/session")), Ok)
    assert len(transport.requests) == 2


@pytest.mark.parametrize(
    "body",
    [{"size": Decimal("0.1234567890123456")}, {"when": datetime(2026, 1, 1, tzinfo=UTC)}],
)
def test_unencodable_body_is_validation_error_and_not_sent(body: dict[str, object]) -> None:
    dispatcher, transport, _ = make([response(200, b"{}")])
    result = dispatcher.send(HttpRequest("POST", "/api/v1/positions", json=body))
    assert isinstance(result, Err)
    assert isinstance(result.error, ValidationError)
    assert transport.requests == []


def test_throttle_waits_like_send() -> None:
    clock = FakeClock()
    windows = {kind: SlidingWindow(1, 1.0) for kind in RequestKind}
    dispatcher = Dispatcher(
        FakeTransport([]), clock, RateLimiter(clock, windows), RetryPolicy(), rand=lambda: 0.0
    )
    dispatcher.throttle("GET", "/api/v1/accounts")
    assert clock.sleeps == []
    dispatcher.throttle("GET", "/api/v1/accounts")
    assert clock.sleeps
    assert clock.sleeps[-1] > 0


def test_retry_log_names_the_resource_but_not_the_deal(caplog: pytest.LogCaptureFixture) -> None:
    # Contract runs log at INFO into public CI output; a deal id there is an account detail.
    dispatcher, _, _ = make([response(429, headers={"Retry-After": "1"}), response(200, b"{}")])
    with caplog.at_level(logging.INFO, logger="capitalcom"):
        dispatcher.send(HttpRequest("DELETE", "/api/v1/positions/DEAL-SECRET-1"))
    assert "DELETE /api/v1/positions/{id}" in caplog.text
    assert "SECRET" not in caplog.text


def test_retry_log_masks_the_id_inside_the_error_text(caplog: pytest.LogCaptureFixture) -> None:
    # A transport error names the request it failed on, raw path included.
    path = "/api/v1/confirms/REF-SECRET-1"
    reset = TransportError(f"GET {path}: ConnectionError", reached_server=True)
    dispatcher, _, _ = make([reset, response(200, b"{}")])
    with caplog.at_level(logging.INFO, logger="capitalcom"):
        dispatcher.send(HttpRequest("GET", path))
    assert "GET /api/v1/confirms/{id}: ConnectionError" in caplog.text
    assert "SECRET" not in caplog.text


def test_outcome_unknown_chains_its_cause_as_raise_from_would() -> None:
    cause = TransportError("read timeout", reached_server=True)
    error = outcome_unknown("POST", "/api/v1/positions", cause)
    assert (error.method, error.path) == ("POST", "/api/v1/positions")
    assert error.__cause__ is cause
    assert error.__suppress_context__
