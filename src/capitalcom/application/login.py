"""Wire format of login and account switch: what is sent and what a valid answer must carry."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from capitalcom.application.ports import HttpRequest, HttpResponse
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.retry import SESSION_PATH
from capitalcom.domain.errors import ApiError, CapitalComError, ResponseFormatError

# The answer to PUT /session naming the account that is already active. PUT /session is
# retried after a lost response, so a retry can reach a session the first attempt already
# switched; that answer means the switch happened. The stage 2a contract probe pins the code.
SWITCH_ALREADY_ACTIVE = "error.not-different.accountId"


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
