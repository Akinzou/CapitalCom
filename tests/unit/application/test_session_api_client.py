import threading
import time
from collections.abc import Sequence

from capitalcom.application.api_client import ApiClient
from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.ports import HttpRequest, HttpResponse
from capitalcom.application.rate_limiter import RateLimiter, RequestKind, TokenBucket
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import RetryPolicy
from capitalcom.application.session import Credentials, SessionManager, SessionTokens
from capitalcom.domain.errors import AuthenticationError, ResponseFormatError, TransportError
from capitalcom.domain.secret import Secret
from tests.fakes import FakeClock, FakeTransport, response

CREDS = Credentials(Secret("key-123"), "me@example.com", Secret("pw-456"))


def login_ok(n: int = 1) -> HttpResponse:
    return response(200, b"{}", {"CST": f"cst-{n}", "X-SECURITY-TOKEN": f"xst-{n}"})


def make(
    script: Sequence[HttpResponse | TransportError],
) -> tuple[ApiClient, SessionManager, FakeTransport, FakeClock]:
    clock = FakeClock()
    transport = FakeTransport(script)
    # Unthrottled buckets keep the fake clock still, so the expiry arithmetic stays exact.
    buckets = {kind: TokenBucket(1e9, 1_000_000) for kind in RequestKind}
    dispatcher = Dispatcher(transport, clock, RateLimiter(clock, buckets), RetryPolicy())
    session = SessionManager(dispatcher, clock, CREDS)
    return ApiClient(dispatcher, session), session, transport, clock


def session_posts(transport: FakeTransport) -> int:
    return sum(r.method == "POST" and r.path == "/api/v1/session" for r in transport.requests)


def test_first_call_logs_in_lazily_and_sends_tokens() -> None:
    api, _, transport, _ = make([login_ok(), response(200, b'{"a": 1}')])
    assert api.call("GET", "/api/v1/accounts") == Ok({"a": 1})
    login, call = transport.requests
    assert login.headers["X-CAP-API-KEY"] == "key-123"
    assert login.json == {
        "identifier": "me@example.com",
        "password": "pw-456",
        "encryptedPassword": False,
    }
    assert call.headers["CST"] == "cst-1"
    assert call.headers["X-SECURITY-TOKEN"] == "xst-1"


def test_session_is_reused_until_570_seconds_idle() -> None:
    api, _, transport, clock = make([login_ok(1), response(200, b"{}")])
    api.call("GET", "/api/v1/accounts")
    clock.advance(569)
    api.call("GET", "/api/v1/accounts")
    assert session_posts(transport) == 1
    clock.advance(570)
    api.call("GET", "/api/v1/accounts")
    assert session_posts(transport) == 2


def test_401_triggers_one_relogin_and_resend() -> None:
    api, _, transport, _ = make(
        [login_ok(1), response(401, b"{}"), login_ok(2), response(200, b"{}")]
    )
    assert isinstance(api.call("GET", "/api/v1/accounts"), Ok)
    assert session_posts(transport) == 2
    assert transport.requests[-1].headers["CST"] == "cst-2"


def test_401_after_relogin_is_returned_without_looping() -> None:
    rejected = response(401, b'{"errorCode":"error.null.client.token"}')
    api, _, transport, _ = make([login_ok(1), rejected, login_ok(2), rejected])
    result = api.call("GET", "/api/v1/accounts")
    assert isinstance(result, Err)
    assert isinstance(result.error, AuthenticationError)
    assert session_posts(transport) == 2
    assert len(transport.requests) == 4


def test_failed_login_is_returned() -> None:
    api, _, _, _ = make([response(401, b'{"errorCode":"error.invalid.api.key"}')])
    result = api.call("GET", "/api/v1/accounts")
    assert isinstance(result, Err)
    assert result.error.error_code == "error.invalid.api.key"  # type: ignore[attr-defined]


def test_missing_cst_header_is_response_format_error() -> None:
    api, _, _, _ = make([response(200, b"{}", {"X-SECURITY-TOKEN": "x"})])
    result = api.call("GET", "/api/v1/accounts")
    assert isinstance(result, Err)
    assert isinstance(result.error, ResponseFormatError)
    assert "CST" in str(result.error)


def test_empty_success_body_is_none() -> None:
    api, _, _, _ = make([login_ok(), response(200, b"")])
    assert api.call("DELETE", "/api/v1/positions/d_1") == Ok(None)


def test_credentials_and_tokens_do_not_leak_in_repr() -> None:
    tokens = SessionTokens(Secret("cst-secret"), Secret("xst-secret"), generation=1)
    assert "pw-456" not in repr(CREDS)
    assert "key-123" not in repr(CREDS)
    assert "cst-secret" not in repr(tokens)
    assert "xst-secret" not in repr(tokens)


def test_stale_invalidate_does_not_drop_a_newer_session() -> None:
    _, session, transport, _ = make([login_ok(1), login_ok(2)])
    old = session.tokens()
    assert isinstance(old, Ok)
    session.invalidate(old.value)
    new = session.tokens()
    assert isinstance(new, Ok)
    session.invalidate(old.value)  # a late thread still holding generation 1
    again = session.tokens()
    assert again == new
    assert session_posts(transport) == 2


def test_logout_deletes_session_and_forgets_tokens() -> None:
    api, session, transport, _ = make([login_ok(), response(200, b"{}")])
    api.call("GET", "/api/v1/accounts")
    assert session.logout() == Ok(None)
    assert transport.requests[-1].method == "DELETE"
    assert transport.requests[-1].path == "/api/v1/session"
    assert transport.requests[-1].headers["CST"] == "cst-1"


def test_logout_without_session_sends_nothing() -> None:
    _, session, transport, _ = make([login_ok()])
    assert session.logout() == Ok(None)
    assert transport.requests == []


class SlowTransport(FakeTransport):
    """Holds each request for a moment, so racing threads overlap inside a login."""

    def send(self, request: HttpRequest) -> Result[HttpResponse, TransportError]:
        # The one real sleep in the unit suite: without a window, an unlocked check-then-login
        # finishes before the next thread starts and the race this test guards cannot happen.
        time.sleep(0.02)
        return super().send(request)


def test_concurrent_expiry_logs_in_once() -> None:
    clock = FakeClock()
    transport = SlowTransport([login_ok()])
    buckets = {kind: TokenBucket(1e9, 1_000_000) for kind in RequestKind}
    dispatcher = Dispatcher(transport, clock, RateLimiter(clock, buckets), RetryPolicy())
    session = SessionManager(dispatcher, clock, CREDS)
    barrier = threading.Barrier(8)
    results: list[object] = []

    def worker() -> None:
        barrier.wait()
        results.append(session.tokens())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert session_posts(transport) == 1
    assert len(results) == 8
    assert all(r == results[0] for r in results)


def test_success_body_that_is_not_json_is_response_format_error() -> None:
    api, _, _, _ = make([login_ok(), response(200, b"<html>maintenance</html>")])
    result = api.call("GET", "/api/v1/accounts")
    assert isinstance(result, Err)
    assert isinstance(result.error, ResponseFormatError)
    assert "maintenance" in result.error.body


def test_logout_after_idle_timeout_sends_nothing() -> None:
    api, session, transport, clock = make([login_ok(), response(200, b"{}")])
    api.call("GET", "/api/v1/accounts")
    clock.advance(600)
    assert session.logout() == Ok(None)
    assert [r.method for r in transport.requests] == ["POST", "GET"]


def test_logout_answered_401_counts_as_logged_out() -> None:
    api, session, _, _ = make([login_ok(), response(200, b"{}"), response(401, b"{}")])
    api.call("GET", "/api/v1/accounts")
    assert session.logout() == Ok(None)


def test_closed_session_refuses_to_log_in_again() -> None:
    api, session, transport, _ = make([login_ok(), response(200, b"{}")])
    api.call("GET", "/api/v1/accounts")
    assert session.close() == Ok(None)
    result = api.call("GET", "/api/v1/accounts")
    assert isinstance(result, Err)
    assert "closed" in str(result.error)
    assert session_posts(transport) == 1
