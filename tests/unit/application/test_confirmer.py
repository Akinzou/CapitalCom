import json
from collections.abc import Sequence

import pytest

from capitalcom.application.api_client import ApiClient
from capitalcom.application.confirmer import DealConfirmer
from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.ports import HttpResponse
from capitalcom.application.rate_limiter import RateLimiter, RequestKind, TokenBucket
from capitalcom.application.result import Err, Ok
from capitalcom.application.retry import RetryPolicy
from capitalcom.application.session import Credentials, SessionManager
from capitalcom.domain.errors import (
    ApiError,
    ConfirmationTimeoutError,
    DealRejectedError,
    OutcomeUnknownError,
)
from capitalcom.domain.secret import Secret
from tests.fakes import FakeClock, FakeTransport, response

LOGIN = response(
    200,
    b'{"currentAccountId": "A"}',
    {"CST": "confirm-cst-0001", "X-SECURITY-TOKEN": "confirm-xst-0001"},
)
NOT_READY = response(400, b'{"errorCode":"error.invalid.dealReference"}')


def confirm_body(status: str | None, **extra: object) -> HttpResponse:
    payload: dict[str, object] = {"dealReference": "o_1", **extra}
    if status is not None:
        payload["dealStatus"] = status
    return response(200, json.dumps(payload).encode())


def make(
    script: Sequence[HttpResponse], timeout_s: float = 5.0
) -> tuple[DealConfirmer, FakeTransport, FakeClock]:
    clock = FakeClock()
    transport = FakeTransport([LOGIN, *script])
    buckets = {kind: TokenBucket(1e9, 1_000_000) for kind in RequestKind}
    dispatcher = Dispatcher(transport, clock, RateLimiter(clock, buckets), RetryPolicy())
    session = SessionManager(
        dispatcher, clock, Credentials(Secret("confirm-key-0001"), "id", Secret("confirm-pw-0001"))
    )
    return DealConfirmer(ApiClient(dispatcher, session), clock, timeout_s), transport, clock


def test_not_found_and_not_ready_are_polled_until_accepted() -> None:
    confirmer, _, clock = make(
        [response(404, b"{}"), NOT_READY, confirm_body("ACCEPTED", dealId="d_1")]
    )
    result = confirmer.confirm("o_1")
    assert isinstance(result, Ok)
    assert result.value.deal_id == "d_1"
    assert clock.sleeps == [0.1, 0.1]


def test_pending_outcome_is_polled() -> None:
    confirmer, _, clock = make([confirm_body(None), confirm_body("ACCEPTED", dealId="d_1")])
    assert isinstance(confirmer.confirm("o_1"), Ok)
    assert clock.sleeps == [0.1]


def test_rejected_is_deal_rejected_error_with_reason() -> None:
    confirmer, _, _ = make([confirm_body("REJECTED", reason="INSUFFICIENT_FUNDS")])
    result = confirmer.confirm("o_1")
    assert isinstance(result, Err)
    assert isinstance(result.error, DealRejectedError)
    assert result.error.reason == "INSUFFICIENT_FUNDS"
    assert result.error.deal_reference == "o_1"


def test_never_ready_times_out_after_about_five_seconds() -> None:
    confirmer, _, clock = make([response(404, b"{}")])
    result = confirmer.confirm("o_1")
    assert isinstance(result, Err)
    assert isinstance(result.error, ConfirmationTimeoutError)
    assert 4.9 <= clock.monotonic() <= 5.2


def test_other_errors_return_at_once_as_outcome_unknown() -> None:
    # The deal was already submitted: whatever stopped polling, its outcome is unknown, and a
    # caller must not read a "never sent" transport error as permission to resend.
    confirmer, transport, clock = make([response(500, b'{"errorCode":"error.internal"}')])
    result = confirmer.confirm("o_1")
    assert isinstance(result, Err)
    assert isinstance(result.error, OutcomeUnknownError)
    assert type(result.error.__cause__) is ApiError
    assert clock.sleeps == []
    assert len(transport.requests) == 2


def test_other_400_codes_return_at_once() -> None:
    confirmer, _, clock = make([response(400, b'{"errorCode":"error.other"}')])
    assert isinstance(confirmer.confirm("o_1"), Err)
    assert clock.sleeps == []


def test_unknown_deal_status_is_returned_not_polled() -> None:
    confirmer, _, clock = make([confirm_body("WEIRD")])
    result = confirmer.confirm("o_1")
    assert isinstance(result, Err)
    assert isinstance(result.error, OutcomeUnknownError)
    assert "WEIRD" in str(result.error.__cause__)
    assert clock.sleeps == []


def test_malformed_payload_is_outcome_unknown() -> None:
    confirmer, _, _ = make([response(200, b"[1, 2]")])
    result = confirmer.confirm("o_1")
    assert isinstance(result, Err)
    assert isinstance(result.error, OutcomeUnknownError)


def test_reference_is_escaped_as_one_path_segment() -> None:
    confirmer, transport, _ = make([confirm_body("ACCEPTED", dealId="d_1")])
    confirmer.confirm("o_/x")
    assert transport.requests[-1].path == "/api/v1/confirms/o_%2Fx"


@pytest.mark.parametrize("timeout", [0.0, -1.0])
def test_non_positive_timeout_still_checks_once(timeout: float) -> None:
    confirmer, transport, _ = make([confirm_body("ACCEPTED", dealId="d_1")], timeout)
    assert isinstance(confirmer.confirm("o_1"), Ok)
    assert len(transport.requests) == 2


def test_poll_returns_none_while_pending() -> None:
    confirmer, transport, _ = make(
        [NOT_READY, confirm_body(None), confirm_body("ACCEPTED", dealId="D1")]
    )
    assert confirmer.poll("o_1") is None
    assert confirmer.poll("o_1") is None
    polled = confirmer.poll("o_1")
    assert isinstance(polled, Ok)
    assert polled.value.deal_id == "D1"
    assert transport.requests[-1].path == "/api/v1/confirms/o_1"
