import logging
from collections.abc import Iterator

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.errors import ApiError, AuthenticationError, CapitalComError

DEMO = "https://demo-api-capital.backend-capital.com"
TOKENS = {"CST": "facade-cst-01", "X-SECURITY-TOKEN": "facade-xst-01"}


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(f"{DEMO}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        mock.get(f"{DEMO}/api/v1/ping", json={"status": "OK"})
        yield mock


def new_client() -> CapitalCom:
    return CapitalCom("facade-key-01", "me@example.com", "facade-pw-01")


def calls(mock: responses.RequestsMock) -> list[tuple[str | None, str]]:
    return [(c.request.method, c.request.path_url) for c in mock.calls]


def test_context_manager_logs_in_pings_and_logs_out(api: responses.RequestsMock) -> None:
    api.delete(f"{DEMO}/api/v1/session", json={"status": "SUCCESS"})
    with new_client() as cc:
        cc.session.ping()
    assert calls(api) == [
        ("POST", "/api/v1/session"),
        ("GET", "/api/v1/ping"),
        ("DELETE", "/api/v1/session"),
    ]


@pytest.mark.parametrize(
    ("api_key", "identifier", "password"), [("", "i", "p"), ("k", "", "p"), ("k", "i", "")]
)
def test_empty_credentials_are_refused(api_key: str, identifier: str, password: str) -> None:
    with pytest.raises(ValueError, match="empty"):
        CapitalCom(api_key, identifier, password)


def test_repr_shows_environment_only() -> None:
    cc = new_client()
    assert repr(cc) == "CapitalCom(environment=Environment.DEMO)"
    assert "facade-pw-01" not in repr(cc)
    assert "me@example.com" not in repr(cc)


def test_errors_are_raised_as_typed_exceptions() -> None:
    with responses.RequestsMock() as mock:
        mock.post(f"{DEMO}/api/v1/session", status=401, json={"errorCode": "error.invalid.api.key"})
        with pytest.raises(AuthenticationError) as caught:
            new_client().session.ping()
    assert caught.value.error_code == "error.invalid.api.key"


def test_exit_keeps_the_original_exception_and_warns_about_logout(
    api: responses.RequestsMock, caplog: pytest.LogCaptureFixture
) -> None:
    api.delete(f"{DEMO}/api/v1/session", status=400, json={"errorCode": "error.x"})

    def failing_block() -> None:
        with new_client() as cc:
            cc.session.ping()
            raise RuntimeError("caller bug")

    with caplog.at_level(logging.WARNING, logger="capitalcom"), pytest.raises(RuntimeError):
        failing_block()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "logout" in warnings[0].getMessage()


def test_close_raises_when_logout_fails(api: responses.RequestsMock) -> None:
    api.delete(f"{DEMO}/api/v1/session", status=400, json={"errorCode": "error.x"})
    cc = new_client()
    cc.session.ping()
    with pytest.raises(ApiError, match=r"error.x"):
        cc.close()


def test_close_twice_logs_out_once(api: responses.RequestsMock) -> None:
    api.delete(f"{DEMO}/api/v1/session", json={"status": "SUCCESS"})
    cc = new_client()
    cc.session.ping()
    cc.close()
    cc.close()
    assert calls(api).count(("DELETE", "/api/v1/session")) == 1


def test_unused_client_closes_without_requests(api: responses.RequestsMock) -> None:
    with new_client():
        pass
    assert calls(api) == []


def test_explicit_logout_then_ping_logs_in_again(api: responses.RequestsMock) -> None:
    api.delete(f"{DEMO}/api/v1/session", json={"status": "SUCCESS"})
    cc = new_client()
    cc.session.ping()
    cc.session.logout()
    cc.session.ping()
    assert calls(api).count(("POST", "/api/v1/session")) == 2


def test_public_exports() -> None:
    import capitalcom

    expected = {
        "CapitalClient",
        "CapitalCom",
        "Environment",
        "Direction",
        "RetryPolicy",
        "DealConfirmation",
        "CapitalComError",
        "ValidationError",
        "ApiError",
        "AuthenticationError",
        "NotFoundError",
        "RateLimitError",
        "ResponseFormatError",
        "TransportError",
        "OutcomeUnknownError",
        "DealRejectedError",
        "ConfirmationTimeoutError",
        "SessionInfo",
        "Account",
        "Balance",
        "AccountPreferences",
        "Leverage",
        "Activity",
        "Transaction",
        "Market",
        "MarketNode",
        "NodeContents",
        "MarketDetails",
        "Instrument",
        "DealingRules",
        "RuleValue",
        "MarketSnapshot",
        "PipScale",
        "Resolution",
        "PriceBar",
        "BidAsk",
        "Sentiment",
        "Watchlist",
        "WatchlistCreation",
        "StopLoss",
        "TakeProfit",
        "OrderRequest",
        "WorkingOrderRequest",
        "OrderType",
        "Position",
        "WorkingOrder",
        "SizeAdjustedError",
    }
    assert expected <= set(dir(capitalcom))


def test_use_after_close_raises_and_does_not_log_in(api: responses.RequestsMock) -> None:
    api.delete(f"{DEMO}/api/v1/session", json={"status": "SUCCESS"})
    cc = new_client()
    cc.session.ping()
    cc.close()
    with pytest.raises(CapitalComError, match="closed"):
        cc.session.ping()
    assert calls(api).count(("POST", "/api/v1/session")) == 1


def test_core_exposes_its_clock() -> None:
    from capitalcom.api.composition import build_core
    from capitalcom.application.session import Credentials
    from capitalcom.domain.enums import Environment
    from capitalcom.domain.secret import Secret
    from tests.fakes import FakeClock, FakeTransport

    clock = FakeClock()
    credentials = Credentials(Secret("clk-key-0001"), "me@example.com", Secret("clk-pw-0001"))
    core = build_core(credentials, Environment.DEMO, clock=clock, transport=FakeTransport([]))
    assert core.clock is clock
