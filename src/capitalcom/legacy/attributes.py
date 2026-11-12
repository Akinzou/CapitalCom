"""The 1.0.4 attributes of ``CapitalClient``, backed by the 2.x core instead of copies."""

import requests

from capitalcom.api.composition import Core


class LegacyAttributes:
    """Credentials, ``session`` and ``base_url`` are read-only, and the tokens live in the core.

    The core was built from the credentials, session and host, so assigning a new value would
    be ignored without a word; a read-only property refuses it instead.
    """

    _api_key: str
    _login: str
    _password: str
    _session: requests.Session
    _base_url: str
    _core: Core
    _pending_tokens: tuple[str | None, str | None] = (None, None)

    @property
    def api_key(self) -> str:
        """API key given to the constructor."""
        return self._api_key

    @property
    def login(self) -> str:
        """Login (e-mail address) given to the constructor."""
        return self._login

    @property
    def password(self) -> str:
        """Password given to the constructor."""
        return self._password

    @property
    def session(self) -> requests.Session:
        """The ``requests.Session`` every call goes through; its settings apply."""
        return self._session

    @property
    def base_url(self) -> str:
        """REST base URL of the demo or live environment."""
        return self._base_url

    @property
    def cst(self) -> str | None:
        """Current ``CST`` session token, or the one assigned while there is no session."""
        tokens = self._core.session.current_tokens()
        return tokens.cst.reveal() if tokens is not None else self._pending_tokens[0]

    @cst.setter
    def cst(self, value: str | None) -> None:
        self._set_tokens(value, self.security_token)

    @property
    def security_token(self) -> str | None:
        """Current ``X-SECURITY-TOKEN``, or the one assigned while there is no session."""
        tokens = self._core.session.current_tokens()
        return tokens.security_token.reveal() if tokens is not None else self._pending_tokens[1]

    @security_token.setter
    def security_token(self, value: str | None) -> None:
        self._set_tokens(self.cst, value)

    def _set_tokens(self, cst: str | None, security_token: str | None) -> None:
        # 1.x code restores a saved pair one attribute at a time. Until both halves are
        # present there is no usable session, so the half already assigned is kept here
        # instead of being dropped, which would silently log in afresh on the next call.
        if cst and security_token:
            self._core.session.adopt_tokens(cst, security_token)
            self._pending_tokens = (None, None)
        else:
            self._core.session.adopt_tokens(None, None)
            self._pending_tokens = (cst, security_token)

    @property
    def token_expiry(self) -> float:
        """Epoch seconds when the idle session expires; ``0`` without a session."""
        remaining = self._core.session.idle_remaining_s()
        return 0.0 if remaining is None else self._now() + remaining

    @token_expiry.setter
    def token_expiry(self, value: float) -> None:
        # A past time means "log in again", as it did in 1.0.4. A future time cannot keep a
        # session alive on the server; the core renews it on its own timer instead.
        if value <= self._now():
            self._set_tokens(None, None)

    def _now(self) -> float:
        # The core's clock, not time.time(): the expiry is computed from the session's own
        # timer, and a test or caller that replaces the clock must see both move together.
        return self._core.clock.now_utc().timestamp()

    def _headers(self) -> dict[str, str | None]:
        return {"CST": self.cst, "X-SECURITY-TOKEN": self.security_token}
