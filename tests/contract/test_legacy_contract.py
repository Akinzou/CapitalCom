"""The deprecated 1.x ``CapitalClient`` on demo: open, list and close through the 2.x core.

It never calls list_accounts, get_balance, top_up_demo or test_trade: they log balances or
move money. Its own INFO lines name deal ids, so they are silenced for the run.
"""

import logging

import pytest

from capitalcom.application.session import Credentials
from capitalcom.client import CapitalClient
from tests.contract.conftest import EPIC, Market

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")


def test_legacy_round_trip(
    btc: Market, demo_credentials: Credentials, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="capitalcom.client")
    client = CapitalClient(
        demo_credentials.api_key.reveal(),
        demo_credentials.identifier,
        demo_credentials.password.reveal(),
        demo=True,
    )
    try:
        deal_id = client.open_raw_position(EPIC, float(btc.min_size), "BUY")
        open_ids = {p["position"]["dealId"] for p in client.get_open_positions()}
        log.info("legacy open listed: %s", deal_id in open_ids)
        assert deal_id in open_ids
        assert client.close_position_by_id(deal_id) == "SUCCESS"
        open_ids = {p["position"]["dealId"] for p in client.get_open_positions()}
        assert deal_id not in open_ids
    finally:
        # 1.x has no logout; ended here so the run does not hold a second session for ten
        # minutes against the server's session limit.
        client._core.session.close()
