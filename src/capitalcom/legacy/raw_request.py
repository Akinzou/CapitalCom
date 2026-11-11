"""``CapitalClient._request``: an authenticated request that returns the raw response."""

from typing import Any

import requests

from capitalcom.api.composition import Core
from capitalcom.application.logs import get_logger
from capitalcom.domain.errors import CapitalComError, ValidationError
from capitalcom.infrastructure.requests_transport import tls_verify
from capitalcom.legacy.wiring import LEGACY_TIMEOUT

_log = get_logger(__name__)

# 1.0.4's loop: ten attempts, one re-login on the first 401, a fixed 1 s wait on a 429.
MAX_ATTEMPTS = 10
RATE_LIMIT_WAIT_S = 1.0


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
    if not path.startswith("/") or path.startswith("//"):
        # "@evil.example/x" appended to the host would make evil.example the host, and the
        # session tokens would go there.
        raise ValidationError(f"path must start with a single '/', got {path!r}")
    options = dict(kwargs)
    verify = options.pop("verify", tls_verify(session))
    if verify is not True and not (isinstance(verify, str) and verify):
        raise ValidationError("_request always verifies TLS; verify may be True or a CA path")
    if options.pop("allow_redirects", False) is not False:
        raise ValidationError("_request never follows redirects; they would carry the tokens")
    extra_headers = dict(options.pop("headers", None) or {})
    options.setdefault("timeout", LEGACY_TIMEOUT)
    for attempt in range(MAX_ATTEMPTS):
        tokens = core.session.tokens().unwrap()
        core.dispatcher.throttle(method, path)
        response = session.request(
            method,
            f"{base_url}{path}",
            headers=extra_headers | tokens.headers(),
            verify=verify,
            allow_redirects=False,
            **options,
        )
        if response.status_code == 401 and attempt == 0:
            core.session.invalidate(tokens)
            continue
        if response.status_code == 429:
            _log.warning(
                "rate limited (429) on %s %s; waiting %.1fs", method, path, RATE_LIMIT_WAIT_S
            )
            core.clock.sleep(RATE_LIMIT_WAIT_S)
            continue
        core.session.mark_used()
        return response
    raise CapitalComError(f"Request failed after {MAX_ATTEMPTS} retries: {method} {path}")
