"""``cc.session``: explicit control over the login session."""

from datetime import datetime

from capitalcom.api.composition import Core
from capitalcom.application.ports import HttpRequest
from capitalcom.domain.account import SessionInfo
from capitalcom.domain.parsing import as_mapping, epoch_ms_to_utc, require_int


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

    def info(self) -> SessionInfo:
        """Client, account and streaming endpoint of the live session."""
        body = self._core.api.call("GET", "/api/v1/session").unwrap()
        return SessionInfo.from_api(as_mapping(body, "session"))

    def server_time(self) -> datetime:
        """Server clock as an aware UTC datetime.

        ``GET /api/v1/time`` needs no session, so it is sent without logging in: a caller
        checking clock drift before trading should not spend one of the rate-limited logins.
        """
        response = self._core.dispatcher.send(HttpRequest("GET", "/api/v1/time")).unwrap()
        body = as_mapping(response.json(), "time")
        return epoch_ms_to_utc(require_int(body, "serverTime"), "serverTime")

    def switch_account(self, account_id: str) -> None:
        """Move the session to ``account_id``; later automatic re-logins return to it.

        Requests already in flight on other threads when the switch happens may run on
        either account. Switch before starting work on that account, not while trading.
        """
        self._core.session.switch_account(account_id).unwrap()
