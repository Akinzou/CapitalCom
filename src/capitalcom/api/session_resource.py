"""``cc.session``: explicit control over the login session."""

from capitalcom.api.composition import Core


class SessionResource:
    """Session operations; logging in itself is automatic on the first call."""

    def __init__(self, core: Core) -> None:
        self._core = core

    def ping(self) -> None:
        """Check connectivity and keep the session alive (``GET /api/v1/ping``)."""
        self._core.api.call("GET", "/api/v1/ping").unwrap()

    def logout(self) -> None:
        """End the session now; the next call logs in again."""
        self._core.session.logout().unwrap()
