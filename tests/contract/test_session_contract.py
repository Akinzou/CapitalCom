"""Session lifecycle against the demo server."""

import pytest

from capitalcom.api.composition import Core
from capitalcom.application.result import Ok

pytestmark = pytest.mark.contract


def test_login_then_ping(demo_core: Core) -> None:
    assert demo_core.api.call("GET", "/api/v1/ping").unwrap() == {"status": "OK"}


def test_logout_succeeds(demo_core: Core) -> None:
    demo_core.api.call("GET", "/api/v1/ping").unwrap()
    assert demo_core.session.logout() == Ok(None)


def test_call_after_logout_logs_in_again(demo_core: Core) -> None:
    demo_core.api.call("GET", "/api/v1/ping").unwrap()
    demo_core.session.logout().unwrap()
    assert demo_core.api.call("GET", "/api/v1/ping").unwrap() == {"status": "OK"}
