import logging
from decimal import Decimal

import pytest

from capitalcom.application.json_codec import decode_json, encode_json, path_segment
from capitalcom.application.logs import forget_secret, get_logger, register_secret
from capitalcom.application.ports import HttpRequest, HttpResponse
from capitalcom.application.result import Err, Ok
from capitalcom.domain.errors import NotFoundError, ResponseFormatError, ValidationError


def test_ok_unwrap_returns_value() -> None:
    assert Ok(3).unwrap() == 3


def test_err_unwrap_raises_the_error() -> None:
    with pytest.raises(NotFoundError):
        Err(NotFoundError(404, None, "")).unwrap()


def test_http_request_repr_hides_headers_and_body() -> None:
    request = HttpRequest(
        "POST", "/api/v1/session", {"X-CAP-API-KEY": "hunter2"}, json={"password": "hunter2"}
    )
    assert "hunter2" not in repr(request)
    assert "POST /api/v1/session" in repr(request)


def test_http_response_header_is_case_insensitive() -> None:
    response = HttpResponse(200, {"CST": "t"}, b"")
    assert response.header("cst") == "t"
    assert response.header("missing") is None


def test_http_response_json_decodes_decimals() -> None:
    assert HttpResponse(200, {}, b'{"a": 1.10}').json() == {"a": Decimal("1.10")}


def test_http_response_json_rejects_html() -> None:
    with pytest.raises(ResponseFormatError):
        HttpResponse(502, {}, b"<html>").json()


def test_encode_json_writes_decimal_as_number() -> None:
    assert encode_json({"size": Decimal("0.0010")}) == b'{"size": 0.001}'
    assert encode_json({"level": Decimal("1.1234"), "n": 2}) == b'{"level": 1.1234, "n": 2}'


def test_encode_json_rejects_decimal_a_float_cannot_hold() -> None:
    with pytest.raises(ValidationError, match="size"):
        encode_json({"size": Decimal("1.0000000000000001")})


def test_encode_json_rejects_non_finite_decimal() -> None:
    with pytest.raises(ValidationError):
        encode_json({"level": Decimal("NaN")})


def test_decode_json_keeps_decimal_precision() -> None:
    assert decode_json(b'{"a": 1.10}')["a"] == Decimal("1.10")


def test_path_segment_escapes_slashes() -> None:
    assert path_segment("a/b") == "a%2Fb"
    assert path_segment("../x") == "..%2Fx"


def test_registered_secret_is_redacted_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    token = "tok-redact-me-123"  # noqa: S105 - test value, not a credential
    register_secret(token)
    try:
        with caplog.at_level(logging.DEBUG, logger="capitalcom"):
            get_logger("capitalcom.x").warning("t=%s", token)
            get_logger("capitalcom.x").warning(f"inline {token}")
        assert "t=***" in caplog.text
        assert "inline ***" in caplog.text
        assert token not in caplog.text
    finally:
        forget_secret(token)


def test_forgotten_secret_is_no_longer_redacted(caplog: pytest.LogCaptureFixture) -> None:
    register_secret("old-token-xyz")
    forget_secret("old-token-xyz")
    with caplog.at_level(logging.DEBUG, logger="capitalcom"):
        get_logger("capitalcom.y").warning("t=%s", "old-token-xyz")
    assert "t=old-token-xyz" in caplog.text


def test_library_root_logger_has_null_handler() -> None:
    get_logger("capitalcom.z")
    assert any(isinstance(h, logging.NullHandler) for h in logging.getLogger("capitalcom").handlers)


@pytest.mark.parametrize("value", ["1E+400", "1E-400"])
def test_encode_json_rejects_decimal_outside_double_range(value: str) -> None:
    with pytest.raises(ValidationError, match="level"):
        encode_json({"level": Decimal(value)})
