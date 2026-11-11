"""Deal confirmations: pins the undocumented behaviour the confirmer and stage 3 rely on."""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from capitalcom.api.composition import Core
from capitalcom.application.result import Err
from capitalcom.domain.confirmation import Outcome
from capitalcom.domain.errors import ApiError
from tests.contract.conftest import Market, btc_position_ids, close_position, open_position

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")


def test_open_and_close_are_confirmed(demo_core: Core, btc: Market) -> None:
    opened = open_position(demo_core, btc.min_size)
    log.info(
        "open confirmation: dealId=%s affectedDeals=%s date=%r status=%s",
        opened.deal_id,
        opened.affected_deals,
        opened.raw.get("date"),
        opened.status,
    )
    assert opened.outcome is Outcome.ACCEPTED
    assert opened.deal_id is not None
    assert opened.affected_deals
    # Pins the UTC assumption in to_utc: a naive timestamp in another zone would be off by
    # whole hours.
    assert opened.date is not None
    assert abs(opened.date - datetime.now(UTC)) < timedelta(minutes=5)
    # Observed 2026-11-11 (ADR 0007): the top-level dealId is not the position. The position
    # that opened is affectedDeals[0].dealId, which is what 1.0.4 returned and what every
    # later call on the position must use.
    position_id = opened.affected_deals[0].deal_id
    assert opened.deal_id != position_id
    open_ids = btc_position_ids(demo_core)
    assert position_id in open_ids
    assert opened.deal_id not in open_ids

    closed = close_position(demo_core, position_id)
    log.info("close confirmation: status=%s affectedDeals=%s", closed.status, closed.affected_deals)
    assert closed.outcome is Outcome.ACCEPTED


def test_unknown_reference_is_a_pending_signal(demo_core: Core) -> None:
    result = demo_core.api.call("GET", "/api/v1/confirms/o_doesnotexist")
    assert isinstance(result, Err)
    error = result.error
    assert isinstance(error, ApiError)
    log.info("unknown reference: status=%s errorCode=%s", error.status, error.error_code)
    # DealConfirmer polls on exactly these two signals; anything else would end polling early.
    assert error.status == 404 or (error.status, error.error_code) == (
        400,
        "error.invalid.dealReference",
    )
