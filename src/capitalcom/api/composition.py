"""Composition root: the one place that picks concrete adapters for the ports."""

from collections.abc import Callable
from dataclasses import dataclass

import requests

from capitalcom.application.api_client import ApiClient
from capitalcom.application.confirmer import DealConfirmer
from capitalcom.application.dispatcher import Dispatcher
from capitalcom.application.login import PasswordEncryptor
from capitalcom.application.ports import Clock, HttpTransport
from capitalcom.application.rate_limiter import RateLimiter
from capitalcom.application.retry import RetryPolicy
from capitalcom.application.session import Credentials, SessionManager
from capitalcom.domain.enums import Environment
from capitalcom.infrastructure.requests_transport import RequestsTransport
from capitalcom.infrastructure.system_clock import SystemClock


@dataclass(frozen=True, slots=True)
class Core:
    """The wired application services one client instance uses."""

    dispatcher: Dispatcher
    session: SessionManager
    api: ApiClient
    confirmer: DealConfirmer
    release: Callable[[], None]


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
    return Core(dispatcher, session, api, confirmer, release)


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


def _nothing() -> None:
    """Release hook for an injected transport, whose lifetime belongs to whoever made it."""
