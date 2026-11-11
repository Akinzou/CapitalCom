"""Wire format of login and account switch: what is sent and what a valid answer must carry."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from capitalcom.application.ports import HttpRequest, HttpResponse
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import SESSION_PATH
from capitalcom.domain.errors import ApiError, CapitalComError, ResponseFormatError

ENCRYPTION_KEY_PATH = "/api/v1/session/encryptionKey"

# The answer to PUT /session naming the account that is already active. PUT /session is
# retried after a lost response, so a retry can reach a session the first attempt already
# switched; that answer means the switch happened. The stage 2a contract probe pins the code.
SWITCH_ALREADY_ACTIVE = "error.not-different.accountId"

# (password, base64 server key, server timestamp in ms) -> base64 ciphertext. A plain function
# rather than a port: encrypting crosses no process boundary. It is injected because its
# implementation needs the optional ``cryptography`` package, which the core may not import.
PasswordEncryptor = Callable[[str, str, int], str]


@dataclass(frozen=True, slots=True)
class LoginGrant:
    """What a successful ``POST /session`` hands out."""

    cst: str = field(repr=False)
    security_token: str = field(repr=False)
    account_id: str


def parse_login(response: HttpResponse) -> Result[LoginGrant, CapitalComError]:
    """Read the session tokens and the account the server logged into.

    The account id is required, not optional: without it the manager cannot tell whether the
    session landed on the account the caller selected, and would risk trading on another one.
    """
    cst = response.header("CST")
    security_token = response.header("X-SECURITY-TOKEN")
    if not cst or not security_token:
        missing = "CST" if not cst else "X-SECURITY-TOKEN"
        return Err(_format(response, f"login response lacks {missing}"))
    try:
        body = response.json()
    except ResponseFormatError as error:
        return Err(error)
    account_id = body.get("currentAccountId") if isinstance(body, Mapping) else None
    if not isinstance(account_id, str) or not account_id:
        return Err(_format(response, "login response lacks currentAccountId"))
    return Ok(LoginGrant(cst, security_token, account_id))


def login_request(api_key: str, identifier: str, password: str, *, encrypted: bool) -> HttpRequest:
    """``POST /session`` with a plain or an already encrypted password."""
    body = {"identifier": identifier, "password": password, "encryptedPassword": encrypted}
    return HttpRequest("POST", SESSION_PATH, {"X-CAP-API-KEY": api_key}, json=body)


def encryption_key_request(api_key: str) -> HttpRequest:
    """``GET /session/encryptionKey``; it needs the API key and no session."""
    return HttpRequest("GET", ENCRYPTION_KEY_PATH, {"X-CAP-API-KEY": api_key})


def encrypt_for_login(
    response: HttpResponse, password: str, encryptor: PasswordEncryptor
) -> Result[str, CapitalComError]:
    """Encrypt ``password`` with the key and timestamp from an encryption-key response."""
    try:
        body = response.json()
    except ResponseFormatError as error:
        return Err(error)
    key = body.get("encryptionKey") if isinstance(body, Mapping) else None
    timestamp = body.get("timeStamp") if isinstance(body, Mapping) else None
    if not isinstance(key, str) or not key:
        return Err(_format(response, "encryption key response lacks encryptionKey"))
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        return Err(_format(response, "encryption key response lacks an integer timeStamp"))
    try:
        return Ok(encryptor(password, key, timestamp))
    except ValueError as error:
        return Err(_format(response, str(error)))


def switch_request(auth: Mapping[str, str], account_id: str) -> HttpRequest:
    """``PUT /session`` selecting ``account_id`` for the session ``auth`` belongs to."""
    return HttpRequest("PUT", SESSION_PATH, auth, json={"accountId": account_id})


def is_already_active(error: CapitalComError) -> bool:
    """True when a switch failed only because the account was already selected."""
    return (
        isinstance(error, ApiError)
        and error.status == 400
        and error.error_code == SWITCH_ALREADY_ACTIVE
    )


def _format(response: HttpResponse, detail: str) -> ResponseFormatError:
    return ResponseFormatError(response.status, None, detail)
