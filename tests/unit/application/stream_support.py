"""A real ``SessionManager`` over the fake HTTP transport, for the stream tests."""

from collections.abc import Sequence

from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.ports import HttpResponse
from capitalcom.application.rate_limiter import RateLimiter, RequestKind, TokenBucket
from capitalcom.application.result import Ok
from capitalcom.application.retry import RetryPolicy
from capitalcom.application.session import Credentials, SessionManager
from capitalcom.application.stream_session import StreamSession
from capitalcom.domain.errors import TransportError
from capitalcom.domain.secret import Secret
from tests.fakes import FakeClock, FakeConnection, FakeStreamTransport, FakeTransport, response

URL = "wss://stream.test/connect"
CREDS = Credentials(Secret("key-123"), "me@example.com", Secret("pw-456"))


def login_ok(n: int, account: str = "A") -> HttpResponse:
    body = ('{"currentAccountId": "' + account + '"}').encode()
    return response(200, body, {"CST": f"cst-{n}", "X-SECURITY-TOKEN": f"xst-{n}"})


def make_session(
    clock: FakeClock, logins: int = 3, accounts: Sequence[str] = ()
) -> tuple[SessionManager, FakeTransport]:
    """A session whose n-th login hands out ``cst-n`` on ``accounts[n-1]`` (default ``A``).

    It logs in once before returning.
    """
    named = list(accounts) or ["A"] * logins
    http = FakeTransport([login_ok(n, account) for n, account in enumerate(named, start=1)])
    # Unthrottled buckets keep the fake clock still, so the keepalive arithmetic stays exact.
    buckets = {kind: TokenBucket(1e9, 1_000_000) for kind in RequestKind}
    dispatcher = Dispatcher(http, clock, RateLimiter(clock, buckets), RetryPolicy())
    session = SessionManager(dispatcher, clock, CREDS)
    session.tokens()
    return session, http


def open_stream(
    connections: Sequence[FakeConnection | TransportError], accounts: Sequence[str] = ()
) -> tuple[StreamSession, FakeStreamTransport, FakeClock, SessionManager]:
    clock = FakeClock()
    session, _ = make_session(clock, accounts=accounts)
    transport = FakeStreamTransport(clock, connections)
    stream = StreamSession(transport, session, clock, URL, rand=lambda: 0.0)
    assert stream.open() == Ok(None)
    return stream, transport, clock, session


def next_value(stream: StreamSession) -> object:
    result = stream.next_event()
    assert isinstance(result, Ok), result
    return result.value
