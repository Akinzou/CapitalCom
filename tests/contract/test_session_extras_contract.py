"""Session extras against the demo server: server time, info, encrypted login, switch."""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from capitalcom.api.accounts import AccountsResource
from capitalcom.api.composition import Core, build_core
from capitalcom.api.session_resource import SessionResource
from capitalcom.application.login import SWITCH_ALREADY_ACTIVE, switch_request
from capitalcom.application.result import Err
from capitalcom.application.retry import RetryPolicy
from capitalcom.application.session import Credentials
from capitalcom.domain.enums import Environment
from capitalcom.domain.errors import ApiError

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")


def test_server_time_is_close_to_local_clock(demo_core: Core) -> None:
    server = SessionResource(demo_core).server_time()
    drift = server - datetime.now(UTC)
    log.info("server time drift: %s", drift)
    assert abs(drift) < timedelta(minutes=5)


def test_info_names_the_current_account(demo_core: Core) -> None:
    info = SessionResource(demo_core).info()
    log.info("session info: locale=%s currency=%s", info.locale, info.currency)
    assert info.account_id == demo_core.session.current_account_id


def test_encrypted_password_login(demo_credentials: Credentials) -> None:
    # A second client logs in separately, and back-to-back logins from separate clients can
    # draw 429 (ADR 0007), so this one waits longer between attempts.
    retry = RetryPolicy(max_attempts=6, base_delay_s=1.0)
    core = build_core(demo_credentials, Environment.DEMO, retry=retry, encrypted_password=True)
    try:
        assert core.api.call("GET", "/api/v1/ping").unwrap() == {"status": "OK"}
        log.info("encrypted login accepted")
    finally:
        # Logged, not raised: this probe pins the RSA details, and a cleanup error raised
        # here would replace the login failure it is meant to show.
        logout = core.session.logout()
        if isinstance(logout, Err):
            log.warning("logout of the encrypted-login client failed: %s", logout.error)
        core.release()


def test_probe_switch_to_the_active_account(demo_core: Core) -> None:
    tokens = demo_core.session.tokens().unwrap()
    current = demo_core.session.current_account_id
    assert current is not None
    sent = demo_core.dispatcher.send(switch_request(tokens.headers(), current))
    if not isinstance(sent, Err):
        log.info("switch to the active account answered 200: %s", sent.value.body[:200])
        pytest.fail("switching to the active account succeeded; SWITCH_ALREADY_ACTIVE is moot")
    error = sent.error
    assert isinstance(error, ApiError)
    log.info("switch to the active account: %s %s", error.status, error.error_code)
    assert (error.status, error.error_code) == (400, SWITCH_ALREADY_ACTIVE)


def test_switch_round_trip(demo_core: Core) -> None:
    accounts = AccountsResource(demo_core).list()
    original = demo_core.session.current_account_id
    others = [a.account_id for a in accounts if a.account_id != original]
    if original is None or not others:
        pytest.skip("only one account; nothing to switch to")
    session = SessionResource(demo_core)
    before = demo_core.session.tokens().unwrap()
    try:
        session.switch_account(others[0])
        after = demo_core.session.tokens().unwrap()
        log.info("switch changed tokens: %s", after.generation != before.generation)
        assert session.info().account_id == others[0]
    finally:
        session.switch_account(original)
    assert session.info().account_id == original


def test_login_body_carries_current_account_id(demo_core: Core) -> None:
    # Without it every renewal of a client that switched accounts costs an extra PUT; the
    # probe pins that the documented field is sent. Types and statuses only: ids and
    # balances stay out of the public CI log.
    accounts = AccountsResource(demo_core).list()
    log.info("accounts: %s", json.dumps([(a.account_type, a.status) for a in accounts]))
    assert demo_core.session.current_account_id in {a.account_id for a in accounts}
