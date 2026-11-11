"""HTTP transport on ``requests``, with TLS and redirect handling that callers cannot weaken."""

import requests

from capitalcom.application.json_codec import encode_json
from capitalcom.application.ports import HttpRequest, HttpResponse
from capitalcom.application.result import Err, Ok, Result
from capitalcom.domain.errors import TransportError

# Raised before any byte of the request reached the server, so even a trade is known not to
# have executed. SSLError is deliberately absent: requests raises it for a failed handshake but
# also for TLS dropped while the response was read, after the trade may have been booked.
_NOT_SENT = (requests.exceptions.ConnectTimeout,)


class RequestsTransport:
    """Sends requests to one ``https`` base URL."""

    def __init__(
        self,
        base_url: str,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = (5.0, 15.0),
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("base_url must use https://; credentials never travel in clear text")
        self._base_url = base_url.rstrip("/")
        # A caller-supplied session may be shared with other code, so only our own is closed.
        self._owns_session = session is None
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout

    def send(self, request: HttpRequest) -> Result[HttpResponse, TransportError]:
        """Send one request; network failures come back as ``Err``, never as exceptions."""
        headers = dict(request.headers)
        data = None
        if request.json is not None:
            data = encode_json(request.json)
            headers["Content-Type"] = "application/json"
        try:
            # verify and allow_redirects are passed on every call so an injected session
            # configured with verify=False cannot switch TLS checks off. Redirects are not
            # followed because requests would resend the CST and X-SECURITY-TOKEN headers to
            # the redirect target, which may be another host.
            response = self._session.request(
                method=request.method,
                url=self._base_url + request.path,
                headers=headers,
                params=dict(request.params),
                data=data,
                timeout=self._timeout,
                verify=True,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as error:
            # The exception text can contain the full URL or proxy details; the error names
            # only the call, so nothing beyond method and path reaches logs or tracebacks.
            return Err(
                TransportError(
                    f"{request.method} {request.path}: {type(error).__name__}",
                    reached_server=not isinstance(error, _NOT_SENT),
                )
            )
        return Ok(HttpResponse(response.status_code, dict(response.headers), response.content))

    def close(self) -> None:
        """Release pooled connections of the session this transport created."""
        if self._owns_session:
            self._session.close()
