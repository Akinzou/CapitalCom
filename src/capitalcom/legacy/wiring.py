"""Builds the 2.x core behind one legacy client."""

import requests

from capitalcom.api.composition import Core, build_core
from capitalcom.application.session import Credentials
from capitalcom.domain.enums import Environment
from capitalcom.domain.secret import Secret
from capitalcom.infrastructure.requests_transport import RequestsTransport
from capitalcom.legacy.errors import LegacyTransport

# 1.0.4 had no timeout at all, so a call could hang forever; these are the 2.x defaults.
LEGACY_TIMEOUT = (5.0, 15.0)


def legacy_core(
    api_key: str, login: str, password: str, demo: bool, session: requests.Session
) -> Core:
    """Wire a core that sends through ``session``, so its proxies and adapters apply."""
    environment = Environment.DEMO if demo else Environment.LIVE
    credentials = Credentials(Secret(api_key), login, Secret(password))
    # The client owns the session and 1.x never closed it, so the injected transport is not
    # released by the core either.
    transport = LegacyTransport(RequestsTransport(environment.rest_url, session, LEGACY_TIMEOUT))
    return build_core(credentials, environment, transport=transport)
