import pickle

import pytest

from capitalcom.domain.enums import Direction, Environment
from capitalcom.domain.errors import (
    ApiError,
    AuthenticationError,
    CapitalComError,
    ConfirmationTimeoutError,
    DealRejectedError,
    NotFoundError,
    OutcomeUnknownError,
    RateLimitError,
    ResponseFormatError,
    TransportError,
    ValidationError,
)
from capitalcom.domain.secret import Secret

ALL_ERRORS = [
    ValidationError("bad size"),
    ApiError(400, "error.x", "body"),
    AuthenticationError(401, "error.invalid.api.key", ""),
    NotFoundError(404, None, ""),
    RateLimitError(429, None, "", retry_after=2.0),
    ResponseFormatError(200, None, "{}"),
    TransportError("timeout", reached_server=True),
    OutcomeUnknownError("POST", "/api/v1/positions"),
    DealRejectedError("o_1", "INSUFFICIENT_FUNDS"),
    ConfirmationTimeoutError("o_1"),
]


@pytest.mark.parametrize("error", ALL_ERRORS, ids=lambda e: type(e).__name__)
def test_every_error_is_a_capitalcom_exception(error: Exception) -> None:
    assert isinstance(error, Exception)
    assert isinstance(error, CapitalComError)


@pytest.mark.parametrize(
    "error_type", [AuthenticationError, NotFoundError, RateLimitError, ResponseFormatError]
)
def test_server_errors_are_api_errors(error_type: type[ApiError]) -> None:
    assert issubclass(error_type, ApiError)


def test_api_error_message_has_code_and_truncated_body() -> None:
    error = ApiError(400, "error.x", "b" * 900)
    assert "error.x" in str(error)
    assert str(error).count("b") <= 500
    assert len(error.body) == 500
    assert error.status == 400
    assert error.error_code == "error.x"


def test_error_attributes_are_read_only() -> None:
    error = ApiError(400, "error.x", "")
    with pytest.raises(AttributeError):
        error.status = 500  # type: ignore[misc]


def test_rate_limit_error_keeps_retry_after() -> None:
    assert RateLimitError(429, None, "", retry_after=2.0).retry_after == 2.0


def test_outcome_unknown_names_the_request_and_tells_caller_to_check() -> None:
    message = str(OutcomeUnknownError("POST", "/api/v1/positions"))
    assert "POST /api/v1/positions" in message
    assert "check" in message.lower()


def test_deal_rejected_keeps_reference_and_reason() -> None:
    error = DealRejectedError("o_1", "INSUFFICIENT_FUNDS")
    assert (error.deal_reference, error.reason) == ("o_1", "INSUFFICIENT_FUNDS")


def test_secret_is_masked_in_repr_and_str() -> None:
    secret = Secret("hunter2")
    assert "hunter2" not in repr(secret)
    assert "hunter2" not in str(secret)
    assert repr(secret) == "Secret('***')"
    assert secret.reveal() == "hunter2"


def test_secret_equality_and_unhashable() -> None:
    assert Secret("a") == Secret("a")
    assert Secret("a") != Secret("b")
    assert Secret("a") != "a"
    with pytest.raises(TypeError):
        hash(Secret("a"))


def test_secret_cannot_be_mutated() -> None:
    secret = Secret("a")
    with pytest.raises(AttributeError):
        secret.value = "b"


def test_environment_rest_urls() -> None:
    assert Environment.DEMO.rest_url == "https://demo-api-capital.backend-capital.com"
    assert Environment.LIVE.rest_url == "https://api-capital.backend-capital.com"


def test_direction_values_match_api() -> None:
    assert Direction.BUY == "BUY"
    assert Direction("SELL") is Direction.SELL


@pytest.mark.parametrize("error", ALL_ERRORS, ids=lambda e: type(e).__name__)
def test_errors_survive_pickling(error: CapitalComError) -> None:
    # multiprocessing and concurrent.futures pickle exceptions raised in workers.
    # Round-trips an object this test just built; no external data is ever unpickled.
    clone = pickle.loads(pickle.dumps(error))  # noqa: S301  # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
    assert type(clone) is type(error)
    assert str(clone) == str(error)
