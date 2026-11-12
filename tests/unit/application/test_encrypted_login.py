"""Login with an RSA-encrypted password, and the extra it needs."""

import sys

import pytest

from capitalcom.api.client import CapitalCom
from capitalcom.api.composition import build_core
from capitalcom.application import logs
from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.ports import HttpResponse
from capitalcom.application.rate_limiter import RateLimiter, RequestKind, SlidingWindow
from capitalcom.application.result import Err, Ok
from capitalcom.application.retry import RetryPolicy
from capitalcom.application.session import SessionManager
from capitalcom.domain.enums import Environment
from capitalcom.domain.errors import ResponseFormatError, TransportError, ValidationError
from capitalcom.infrastructure import rsa_password
from tests.fakes import FakeClock, FakeTransport, response
from tests.unit.application.test_session_api_client import CREDS, login_ok

KEY = response(200, b'{"encryptionKey": "a2V5", "timeStamp": 1647440528194}')
CALLS: list[tuple[str, str, int]] = []


def stub_encryptor(password: str, key: str, timestamp: int) -> str:
    CALLS.append((password, key, timestamp))
    if key == "bad":
        raise ValueError("encryption key is not a DER public key")
    if key == "long":
        raise ValidationError("password is too long to encrypt with the server key")
    return f"enc-{len(CALLS)}"


def make(script: list[HttpResponse | TransportError]) -> tuple[SessionManager, FakeTransport]:
    CALLS.clear()
    clock = FakeClock()
    transport = FakeTransport(script)
    windows = {kind: SlidingWindow(1_000_000, 1e-9) for kind in RequestKind}
    dispatcher = Dispatcher(transport, clock, RateLimiter(clock, windows), RetryPolicy())
    return SessionManager(dispatcher, clock, CREDS, encryptor=stub_encryptor), transport


def test_encrypted_login_fetches_a_fresh_key_each_login() -> None:
    session, transport = make([KEY, login_ok(1), KEY, login_ok(2)])
    first = session.tokens()
    assert isinstance(first, Ok)
    session.invalidate(first.value)
    assert isinstance(session.tokens(), Ok)
    key_request, login, *_ = transport.requests
    assert [(r.method, r.path) for r in transport.requests[::2]] == [
        ("GET", "/api/v1/session/encryptionKey")
    ] * 2
    assert key_request.headers == {"X-CAP-API-KEY": "key-123"}
    assert login.json == {
        "identifier": "me@example.com",
        "password": "enc-1",
        "encryptedPassword": True,
    }
    sent = transport.requests[3].json or {}
    assert sent["password"] == "enc-2"  # noqa: S105 - the stub ciphertext, not a password
    assert CALLS[0] == ("pw-456", "a2V5", 1647440528194)


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"encryptionKey": "a2V5"}',
        b'{"encryptionKey": "a2V5", "timeStamp": true}',
        b'{"encryptionKey": 1, "timeStamp": 1}',
        b"[]",
        b"<html>",
    ],
)
def test_malformed_key_response_is_response_format_error(body: bytes) -> None:
    session, transport = make([response(200, body)])
    result = session.tokens()
    assert isinstance(result, Err)
    assert isinstance(result.error, ResponseFormatError)
    assert len(transport.requests) == 1


def test_key_the_encryptor_rejects_is_response_format_error() -> None:
    session, transport = make([response(200, b'{"encryptionKey": "bad", "timeStamp": 1}')])
    result = session.tokens()
    assert isinstance(result, Err)
    assert isinstance(result.error, ResponseFormatError)
    assert "encryption key" in str(result.error)
    assert len(transport.requests) == 1


def test_missing_extra_fails_in_constructor(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every cached cryptography module is blocked, not only the top one: an import of a
    # cached submodule would otherwise succeed without touching the parent.
    for name in [n for n in sys.modules if n == "cryptography" or n.startswith("cryptography.")]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "cryptography", None)
    monkeypatch.delitem(sys.modules, "capitalcom.infrastructure.rsa_password", raising=False)
    with pytest.raises(ImportError, match=r"capitalcom\[encryption\]"):
        CapitalCom("key", "me@example.com", "pw", encrypted_password=True)


def test_failed_key_request_is_returned_without_login() -> None:
    session, transport = make([response(401, b'{"errorCode": "error.invalid.api.key"}')])
    result = session.tokens()
    assert isinstance(result, Err)
    assert [r.method for r in transport.requests] == ["GET"]


def test_installed_extra_encrypts_the_login(monkeypatch: pytest.MonkeyPatch) -> None:
    def fixed(password: str, key: str, timestamp: int) -> str:
        return f"rsa({password},{key},{timestamp})"

    monkeypatch.setattr(rsa_password, "encrypt_password", fixed)
    transport = FakeTransport([KEY, login_ok()])
    core = build_core(CREDS, Environment.DEMO, transport=transport, encrypted_password=True)
    assert isinstance(core.session.tokens(), Ok)
    login = transport.requests[1].json or {}
    assert login["password"] == "rsa(pw-456,a2V5,1647440528194)"  # noqa: S105 - stub output
    assert login["encryptedPassword"] is True


def test_ciphertext_is_forgotten_once_the_login_returns() -> None:
    session, _ = make([KEY, login_ok(1), KEY, login_ok(2)])
    first = session.tokens()
    assert isinstance(first, Ok)
    session.invalidate(first.value)
    session.tokens()
    assert not {"enc-1", "enc-2"} & logs._secrets


def test_password_the_encryptor_refuses_is_validation_error() -> None:
    session, transport = make([response(200, b'{"encryptionKey": "long", "timeStamp": 1}')])
    result = session.tokens()
    assert isinstance(result, Err)
    assert isinstance(result.error, ValidationError)
    assert len(transport.requests) == 1
