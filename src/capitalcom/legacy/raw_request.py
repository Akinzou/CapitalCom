"""``CapitalClient._request``: an authenticated request that returns the raw response."""

from typing import Any

import requests

from capitalcom.api.composition import Core
from capitalcom.application.logs import get_logger
from capitalcom.domain.errors import CapitalComError, ValidationError
from capitalcom.legacy.wiring import LEGACY_TIMEOUT

_log = get_logger(__name__)

# 1.0.4's loop: ten attempts, one re-login on the first 401, a fixed 1 s wait on a 429.
MAX_ATTEMPTS = 10
RATE_LIMIT_WAIT_S = 1.0
_FORCED = ("verify", "allow_redirects")


def send_raw(
    core: Core,
    session: requests.Session,
    base_url: str,
    method: str,
    path: str,
    kwargs: dict[str, Any],
) -> requests.Response:
    """Send through ``session`` with the core's tokens and rate limit; any status is returned.

    It bypasses the dispatcher because 1.0.4 callers read ``status_code`` themselves, and the
    dispatcher turns statuses into errors. TLS checks and the no-redirect rule are therefore
    applied here: a redirect would carry the session tokens to another host.
    """
    forced = [name for name in _FORCED if name in kwargs]
    if forced:
        raise ValidationError(
            f"_request always verifies TLS and never follows redirects; drop {', '.join(forced)}"
        )
    options = dict(kwargs)
    extra_headers = dict(options.pop("headers", None) or {})
    options.setdefault("timeout", LEGACY_TIMEOUT)
    for attempt in range(MAX_ATTEMPTS):
        tokens = core.session.tokens().unwrap()
        core.dispatcher.throttle(method, path)
        response = session.request(
            method,
            f"{base_url}{path}",
            headers=extra_headers | tokens.headers(),
            verify=True,
            allow_redirects=False,
            **options,
        )
        if response.status_code == 401 and attempt == 0:
            core.session.invalidate(tokens)
            continue
        if response.status_code == 429:
            _log.warning("rate limited (429) on %s %s; waiting %.1fs", method, path, 1.0)
            core.clock.sleep(RATE_LIMIT_WAIT_S)
            continue
        core.session.mark_used()
        return response
    raise CapitalComError(f"Request failed after {MAX_ATTEMPTS} retries: {method} {path}")
