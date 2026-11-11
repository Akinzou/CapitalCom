"""Accounts and history against the demo server. No test here tops up the account."""

import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import TypeVar

import pytest

from capitalcom.api.accounts import AccountsResource
from capitalcom.api.composition import Core
from capitalcom.api.history import HistoryResource
from tests.contract.conftest import Market, close_position, open_position

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")
T = TypeVar("T")


def test_accounts_list_parses(demo_core: Core) -> None:
    accounts = AccountsResource(demo_core).list()
    assert accounts
    log.info("account types: %s", sorted({a.account_type for a in accounts}))


def test_preferences_round_trip(demo_core: Core) -> None:
    resource = AccountsResource(demo_core)
    before = resource.preferences()
    log.info("leverage classes: %s", sorted(before.leverages))
    current = {name: leverage.current for name, leverage in before.leverages.items()}
    # Writing back the values just read changes nothing, so there is nothing to restore.
    resource.update_preferences(leverages=current, hedging_mode=before.hedging_mode)
    assert resource.preferences() == before


def _eventually(read: Callable[[], tuple[T, ...]], attempts: int = 10) -> tuple[T, ...]:
    # History is written asynchronously after a deal; an empty read right after the close
    # would prove nothing about parsing, so the read is repeated for a few seconds.
    rows = read()
    for _ in range(attempts):
        if rows:
            break
        time.sleep(1)
        rows = read()
    return rows


def test_history_parses_rows_of_a_fresh_trade(demo_core: Core, btc: Market) -> None:
    # Opening and closing a position guarantees rows exist, so the required fields of
    # Activity and Transaction are checked against real data, not against an empty list.
    opened = open_position(demo_core, btc.min_size)
    close_position(demo_core, opened.affected_deals[0].deal_id)
    history = HistoryResource(demo_core)
    window = timedelta(minutes=10)
    activities = _eventually(lambda: history.activity(last_period=window))
    detailed = history.activity(last_period=window, detailed=True)
    transactions = _eventually(lambda: history.transactions(last_period=timedelta(days=1)))
    log.info(
        "activities: %d (types %s), transactions: %d (types %s)",
        len(activities),
        sorted({a.type for a in activities}),
        len(transactions),
        sorted({t.transaction_type for t in transactions}),
    )
    if detailed:
        log.info("detailed activity keys: %s", sorted(detailed[0].raw))
    assert activities, "no activity after opening and closing a position"
    assert transactions, "no transaction in the last day after closing a position"
