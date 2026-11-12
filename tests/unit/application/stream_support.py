"""A real ``SessionManager`` over the fake HTTP transport, for the stream tests."""

from collections.abc import Sequence

from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.ports import HttpResponse
from capitalcom.application.rate_limiter import RateLimiter, RequestKind, TokenBucket
from capitalcom.application.retry import RetryPolicy
from capitalcom.application.session import Credentials, SessionManager
from capitalcom.domain.secret import Secret
from tests.fakes import FakeClock, FakeTransport, response

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
