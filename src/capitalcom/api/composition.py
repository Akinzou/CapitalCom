"""Composition root: the one place that picks concrete adapters for the ports."""

from collections.abc import Callable
from dataclasses import dataclass

import requests

from capitalcom.application.api_client import ApiClient
from capitalcom.application.confirmer import DealConfirmer
from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.login import PasswordEncryptor
from capitalcom.application.ports import Clock, HttpTransport, StreamTransport
from capitalcom.application.rate_limiter import RateLimiter
from capitalcom.application.retry import RetryPolicy
from capitalcom.application.session import Credentials, SessionManager
from capitalcom.domain.enums import STREAM_URL, Environment
from capitalcom.infrastructure.requests_transport import RequestsTransport, tls_verify
from capitalcom.infrastructure.system_clock import SystemClock


@dataclass(frozen=True, slots=True)
class Core:
    """The wired application services one client instance uses."""

    dispatcher: Dispatcher
    session: SessionManager
    api: ApiClient
    confirmer: DealConfirmer
    release: Callable[[], None]
    environment: Environment
    clock: Clock


def build_core(
    credentials: Credentials,
    environment: Environment,
    *,
    http_session: requests.Session | None = None,
    timeout: tuple[float, float] = (5.0, 15.0),
    retry: RetryPolicy | None = None,
    confirm_timeout_s: float = 5.0,
    clock: Clock | None = None,
    transport: HttpTransport | None = None,
    encrypted_password: bool = False,
) -> Core:
    """Wire the core for ``environment``; ``clock`` and ``transport`` replace the real adapters."""
    encryptor = _load_encryptor() if encrypted_password else None
    clock = clock if clock is not None else SystemClock()
    release: Callable[[], None] = _nothing
    if transport is None:
        owned = RequestsTransport(environment.rest_url, http_session, timeout)
        transport, release = owned, owned.close
    dispatcher = Dispatcher(transport, clock, RateLimiter(clock), retry or RetryPolicy())
    session = SessionManager(dispatcher, clock, credentials, encryptor)
    api = ApiClient(dispatcher, session)
    confirmer = DealConfirmer(api, clock, timeout_s=confirm_timeout_s)
    return Core(dispatcher, session, api, confirmer, release, environment, clock)


def _load_encryptor() -> PasswordEncryptor:
    # Imported here, not at module level, so plain-password users never need cryptography;
    # done before anything is wired so a missing extra fails in the constructor, not at the
    # first trade.
    try:
        from capitalcom.infrastructure.rsa_password import encrypt_password
    except ImportError as error:
        raise ImportError(
            "encrypted_password=True needs the 'encryption' extra: "
            "pip install 'capitalcom[encryption]'"
        ) from error
    return encrypt_password


def stream_transport(http_session: requests.Session | None) -> StreamTransport:
    """The WebSocket transport, trusting the CA bundle an injected session names."""
    # Imported here, so REST-only users never need websockets; called by connect(), so a
    # missing extra fails where streaming is asked for, not in the constructor.
    try:
        from capitalcom.infrastructure.websocket_transport import WebsocketTransport
    except ImportError as error:
        raise ImportError(
            "streaming needs the 'streaming' extra: pip install 'capitalcom[streaming]'"
        ) from error
    return WebsocketTransport(_stream_verify(http_session))


def _stream_verify(http_session: requests.Session | None) -> bool | str:
    # The same merge REST gets from passing tls_verify() on every call, so both trust one
    # bundle: the session's path beats REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE, which apply only
    # when the session names none and trusts the environment. Letting the environment win
    # here would silently widen the trust a user narrowed on the session.
    session = http_session if http_session is not None else requests.Session()
    try:
        explicit = tls_verify(session)
        settings = session.merge_environment_settings(STREAM_URL, {}, None, explicit, None)
    finally:
        if http_session is None:
            session.close()
    verify = settings["verify"]
    return verify if isinstance(verify, str) and verify else True


def _nothing() -> None:
    """Release hook for an injected transport, whose lifetime belongs to whoever made it."""
