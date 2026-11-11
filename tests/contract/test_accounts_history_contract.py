"""Accounts and history against the demo server. No test here tops up the account."""

import logging
from datetime import timedelta

import pytest

from capitalcom.api.accounts import AccountsResource
from capitalcom.api.composition import Core
from capitalcom.api.history import HistoryResource

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")


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


def test_history_reads(demo_core: Core) -> None:
    history = HistoryResource(demo_core)
    activities = history.activity(last_period=timedelta(hours=1))
    transactions = history.transactions(last_period=timedelta(days=1))
    log.info("activities: %d, transactions: %d", len(activities), len(transactions))
    assert isinstance(activities, tuple)
    assert isinstance(transactions, tuple)
