"""Fixtures for contract tests against the Capital.com DEMO server.

Only the demo host is reachable from here: the environment is the literal ``Environment.DEMO``
and its URL is asserted below, and nothing reads a host from the environment or options.
"""

import logging
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from capitalcom.api.composition import Core, build_core
from capitalcom.api.orders import OrdersResource
from capitalcom.application.result import Err
from capitalcom.application.session import Credentials
from capitalcom.domain.confirmation import DealConfirmation
from capitalcom.domain.enums import Environment
from capitalcom.domain.parsing import to_decimal
from capitalcom.domain.secret import Secret

DEMO_URL = "https://demo-api-capital.backend-capital.com"
EPIC = "BTCUSD"  # trades around the clock, so nightly runs rarely meet a closed market
SECRET_NAMES = ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_PASSWORD")

log = logging.getLogger("contract")


# One client for the whole run, as a bot would use: its rate limiter then spaces every login,
# whereas a client per test let back-to-back logins from different tests hit the server's
# session limit (429 error.too-many.requests, observed 2026-11-11).
@pytest.fixture(scope="session")
def demo_credentials() -> Credentials:
    assert Environment.DEMO.rest_url == DEMO_URL
    values = [os.environ.get(name, "") for name in SECRET_NAMES]
    if not all(values):
        missing = [n for n, v in zip(SECRET_NAMES, values, strict=True) if not v]
        if os.environ.get("CI"):
            pytest.fail(f"contract secrets missing in CI: {missing}")
        pytest.skip(f"contract secrets not set: {missing}")
    api_key, identifier, password = values
    return Credentials(Secret(api_key), identifier, Secret(password))


@pytest.fixture(scope="session")
def demo_core(demo_credentials: Credentials) -> Iterator[Core]:
    core = build_core(demo_credentials, Environment.DEMO)
    yield core
    try:
        logout = core.session.logout()
        assert not isinstance(logout, Err), f"logout failed: {logout}"
    finally:
        core.release()


@dataclass(frozen=True)
class Market:
    """BTCUSD dealing rules read from the server, so sizes stay valid if the rules change."""

    min_size: Decimal


def btc_position_ids(core: Core) -> dict[str, Decimal]:
    """Open BTCUSD positions on the demo account, by deal id, with their sizes."""
    payload = core.api.call("GET", "/api/v1/positions").unwrap()
    found: dict[str, Decimal] = {}
    for item in payload["positions"]:
        if item["market"]["epic"] == EPIC:
            position = item["position"]
            found[position["dealId"]] = to_decimal(position["size"], "size")
    return found


def close_position(core: Core, deal_id: str) -> DealConfirmation:
    """Close a whole position through the documented endpoint and confirm it."""
    closed = core.api.call("DELETE", f"/api/v1/positions/{deal_id}").unwrap()
    return core.confirmer.confirm(closed["dealReference"]).unwrap()


def open_position(core: Core, size: Decimal) -> DealConfirmation:
    """Open a BUY position of ``size`` and confirm it."""
    body: Mapping[str, Any] = {"epic": EPIC, "direction": "BUY", "size": size}
    opened = core.api.call("POST", "/api/v1/positions", json=body).unwrap()
    return core.confirmer.confirm(opened["dealReference"]).unwrap()


@pytest.fixture
def btc(demo_core: Core) -> Iterator[Market]:
    """BTCUSD rules; afterwards closes every BTCUSD position the test opened.

    Cleanup compares with a snapshot taken before the test, so it also catches positions whose
    confirmation never arrived, and never touches positions that existed before the run.
    """
    details = demo_core.api.call("GET", f"/api/v1/markets/{EPIC}").unwrap()
    status = details["snapshot"]["marketStatus"]
    if status != "TRADEABLE":
        pytest.skip(f"{EPIC} {status}")
    rules = details["dealingRules"]
    log.info("BTCUSD dealing rules: %s", rules)
    before = set(btc_position_ids(demo_core))
    yield Market(min_size=to_decimal(rules["minDealSize"]["value"], "minDealSize"))
    leftovers = set(btc_position_ids(demo_core)) - before
    for deal_id in sorted(leftovers):
        # No id in the message: the contract log is public.
        log.warning("closing a position left by the test")
        close_position(demo_core, deal_id)
    remaining = set(btc_position_ids(demo_core)) - before
    assert not remaining, f"{len(remaining)} position(s) opened by the run are still open"


def btc_order_ids(core: Core) -> set[str]:
    """Working orders on BTCUSD of the demo account."""
    return {order.deal_id for order in OrdersResource(core).list() if order.epic == EPIC}


@pytest.fixture
def btc_orders(demo_core: Core) -> Iterator[None]:
    """Afterwards cancels every BTCUSD order the test placed, and none that existed before.

    Every cancel is tried even when one fails, so one refusal cannot leave the rest open.
    Failures are reported by type only: the log is public, and ids do not belong in it.
    """
    before = btc_order_ids(demo_core)
    yield
    orders = OrdersResource(demo_core)
    failures: list[str] = []
    for deal_id in sorted(btc_order_ids(demo_core) - before):
        log.warning("cancelling an order left by the test")
        try:
            orders.cancel(deal_id)
        except Exception as error:  # noqa: BLE001 - every order must get its cancel attempt
            failures.append(type(error).__name__)
    if failures:
        pytest.fail(f"{len(failures)} order cancel(s) failed: {', '.join(failures)}")
    assert not btc_order_ids(demo_core) - before, "orders placed by the run are still open"
