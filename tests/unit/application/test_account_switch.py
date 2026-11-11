"""Account switch and the selected account surviving every re-login."""

import json

from capitalcom.application.login import SWITCH_ALREADY_ACTIVE, LoginGrant, parse_login
from capitalcom.application.ports import HttpRequest, HttpResponse
from capitalcom.application.result import Err, Ok
from capitalcom.domain.errors import ApiError, ResponseFormatError, ValidationError
from tests.fakes import response
from tests.unit.application.test_session_api_client import login_ok, make

OK = response(200, b"{}")


def switched(headers: dict[str, str] | None = None) -> HttpResponse:
    return response(200, b'{"trailingStopsEnabled": false}', headers)


def rejected(code: str) -> HttpResponse:
    return response(400, json.dumps({"errorCode": code}).encode())


def shape(requests: list[HttpRequest]) -> list[tuple[str, str, object]]:
    return [(r.method, r.path, r.json and r.json.get("accountId")) for r in requests]


def test_switch_sends_put_and_records_account() -> None:
    _, session, transport, _ = make([login_ok(), switched()])
    assert session.switch_account("B") == Ok(None)
    assert shape(transport.requests) == [
        ("POST", "/api/v1/session", None),
        ("PUT", "/api/v1/session", "B"),
    ]
    assert transport.requests[1].headers["CST"] == "cst-1"
    assert session.current_account_id == "B"


def test_switch_to_current_account_sends_nothing() -> None:
    _, session, transport, _ = make([login_ok()])
    assert session.switch_account("A") == Ok(None)
    assert [r.method for r in transport.requests] == ["POST"]
    assert session.current_account_id == "A"


def test_switch_rejects_empty_account_id() -> None:
    _, session, transport, _ = make([login_ok()])
    result = session.switch_account("")
    assert isinstance(result, Err)
    assert isinstance(result.error, ValidationError)
    assert transport.requests == []


def test_switch_adopts_tokens_returned_by_put() -> None:
    new_tokens = {"CST": "cst-sw", "X-SECURITY-TOKEN": "xst-sw"}
    api, session, transport, _ = make([login_ok(), switched(new_tokens), OK])
    session.switch_account("B")
    api.call("GET", "/api/v1/accounts")
    assert transport.requests[-1].headers["CST"] == "cst-sw"
    assert transport.requests[-1].headers["X-SECURITY-TOKEN"] == "xst-sw"


def test_relogin_after_idle_reapplies_selected_account() -> None:
    api, session, transport, clock = make([login_ok(1), switched(), login_ok(2), switched(), OK])
    session.switch_account("B")
    clock.advance(600)
    assert isinstance(api.call("GET", "/api/v1/accounts"), Ok)
    assert shape(transport.requests[2:]) == [
        ("POST", "/api/v1/session", None),
        ("PUT", "/api/v1/session", "B"),
        ("GET", "/api/v1/accounts", None),
    ]
    assert transport.requests[3].headers["CST"] == "cst-2"
    assert session.current_account_id == "B"


def test_relogin_after_401_reapplies_selected_account() -> None:
    script = [login_ok(1), switched(), response(401, b"{}"), login_ok(2), switched(), OK]
    api, session, transport, _ = make(script)
    session.switch_account("B")
    assert isinstance(api.call("GET", "/api/v1/accounts"), Ok)
    assert shape(transport.requests[3:]) == [
        ("POST", "/api/v1/session", None),
        ("PUT", "/api/v1/session", "B"),
        ("GET", "/api/v1/accounts", None),
    ]


def test_failed_reapply_returns_error_and_hands_out_no_tokens() -> None:
    script = [login_ok(1), switched(), login_ok(2), rejected("error.invalid.accountId"), OK]
    api, session, transport, clock = make(script)
    session.switch_account("B")
    clock.advance(600)
    result = api.call("GET", "/api/v1/accounts")
    assert isinstance(result, Err)
    assert isinstance(result.error, ApiError)
    assert result.error.status == 400
    assert all(r.path == "/api/v1/session" for r in transport.requests)
    assert session.current_account_id is None
    # The session the failed re-apply opened is ended, not left to count against the limit.
    logout = transport.requests[-1]
    assert (logout.method, logout.headers["CST"]) == ("DELETE", "cst-2")


def test_switch_answered_already_active_counts_as_success() -> None:
    _, session, _, _ = make([login_ok(), rejected(SWITCH_ALREADY_ACTIVE)])
    assert session.switch_account("B") == Ok(None)
    assert session.current_account_id == "B"


def test_switch_answered_401_logs_in_again_targeting_the_account() -> None:
    script = [login_ok(1), response(401, b"{}"), login_ok(2), switched()]
    _, session, transport, _ = make(script)
    session.tokens()
    assert session.switch_account("B") == Ok(None)
    assert shape(transport.requests[2:]) == [
        ("POST", "/api/v1/session", None),
        ("PUT", "/api/v1/session", "B"),
    ]
    assert transport.requests[3].headers["CST"] == "cst-2"


def test_failed_switch_keeps_previous_selection() -> None:
    script = [login_ok(1), switched(), rejected("error.invalid.accountId"), login_ok(2)]
    script += [switched(), OK]
    api, session, transport, clock = make(script)
    session.switch_account("B")
    result = session.switch_account("C")
    assert isinstance(result, Err)
    assert session.current_account_id == "B"
    clock.advance(600)
    api.call("GET", "/api/v1/accounts")
    assert shape(transport.requests[3:5]) == [
        ("POST", "/api/v1/session", None),
        ("PUT", "/api/v1/session", "B"),
    ]


def test_login_with_malformed_current_account_id_is_response_format_error() -> None:
    tokens = {"CST": "c", "X-SECURITY-TOKEN": "x"}
    for body in (b'{"currentAccountId": ""}', b'{"currentAccountId": 5}', b"[]", b"not json"):
        result = parse_login(response(200, body, tokens))
        assert isinstance(result, Err), body
        assert isinstance(result.error, ResponseFormatError)


def test_login_grant_hides_tokens() -> None:
    result = parse_login(login_ok(7))
    assert result == Ok(LoginGrant("cst-7", "xst-7", "A"))
    assert "cst-7" not in repr(result)
    assert "xst-7" not in repr(result)


def test_switch_returns_login_failure() -> None:
    _, session, transport, _ = make([rejected("error.invalid.details")])
    result = session.switch_account("B")
    assert isinstance(result, Err)
    assert [r.method for r in transport.requests] == ["POST"]


def test_switch_after_401_needs_no_put_when_login_lands_on_the_target() -> None:
    script = [login_ok(1), switched(), response(401, b"{}"), login_ok(2)]
    _, session, transport, _ = make(script)
    session.switch_account("B")
    assert session.switch_account("A") == Ok(None)
    assert [r.method for r in transport.requests] == ["POST", "PUT", "PUT", "POST"]
    assert session.current_account_id == "A"


def test_switch_after_expiry_logs_in_straight_to_the_new_account() -> None:
    script = [login_ok(1), switched(), login_ok(2), switched()]
    _, session, transport, clock = make(script)
    session.switch_account("B")
    clock.advance(600)
    assert session.switch_account("C") == Ok(None)
    assert shape(transport.requests[2:]) == [
        ("POST", "/api/v1/session", None),
        ("PUT", "/api/v1/session", "C"),
    ]


def test_unreachable_selection_does_not_block_switching_away() -> None:
    script = [login_ok(1), switched(), login_ok(2), rejected("error.invalid.accountId"), OK]
    script += [login_ok(3)]
    api, session, transport, clock = make(script)
    session.switch_account("B")
    clock.advance(600)
    assert isinstance(api.call("GET", "/api/v1/accounts"), Err)
    assert session.switch_account("A") == Ok(None)
    assert [r.method for r in transport.requests[5:]] == ["POST"]
    assert session.current_account_id == "A"


def test_login_without_current_account_id_still_logs_in() -> None:
    tokens = {"CST": "c", "X-SECURITY-TOKEN": "x"}
    assert parse_login(response(200, b"{}", tokens)) == Ok(LoginGrant("c", "x", None))


def test_reapply_when_login_does_not_name_the_account_sends_put() -> None:
    unnamed = response(200, b"{}", {"CST": "cst-2", "X-SECURITY-TOKEN": "xst-2"})
    script = [login_ok(1), switched(), unnamed, rejected(SWITCH_ALREADY_ACTIVE), OK]
    api, session, transport, clock = make(script)
    session.switch_account("B")
    clock.advance(600)
    assert isinstance(api.call("GET", "/api/v1/accounts"), Ok)
    assert shape(transport.requests[2:4]) == [
        ("POST", "/api/v1/session", None),
        ("PUT", "/api/v1/session", "B"),
    ]
    assert session.current_account_id == "B"
