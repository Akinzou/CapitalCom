"""Builds the 2.x core behind one legacy client."""

import requests

from capitalcom.api.composition import Core, build_core
from capitalcom.application.session import Credentials
from capitalcom.domain.enums import Environment
from capitalcom.domain.secret import Secret

# 1.0.4 had no timeout at all, so a call could hang forever; these are the 2.x defaults.
LEGACY_TIMEOUT = (5.0, 15.0)


def legacy_core(
    api_key: str, login: str, password: str, demo: bool, session: requests.Session
) -> Core:
    """Wire a core that sends through ``session``, so its proxies and adapters apply."""
    environment = Environment.DEMO if demo else Environment.LIVE
    credentials = Credentials(Secret(api_key), login, Secret(password))
    return build_core(credentials, environment, http_session=session, timeout=LEGACY_TIMEOUT)
