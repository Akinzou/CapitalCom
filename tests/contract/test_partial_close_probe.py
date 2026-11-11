"""Probe of the undocumented ``DELETE /api/v1/positions`` with a ``size`` in the body.

1.0.4's ``close_position_by_id(id, size=...)`` relies on it to close part of a position. This
test pins what the demo server actually does with it (ADR 0007).
"""

import logging

import pytest

from capitalcom.api.composition import Core
from capitalcom.application.result import Err
from capitalcom.domain.errors import NotFoundError
from tests.contract.conftest import Market, open_position

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")


def test_legacy_partial_close_endpoint_closes_the_whole_position(
    demo_core: Core, btc: Market
) -> None:
    # Observed 2026-11-11 (ADR 0007): the size in the body is ignored and the whole position
    # is closed. Stage 3 therefore refuses close_position_by_id(id, size=...) instead of
    # silently closing more than the caller asked for. If this test starts failing, the
    # endpoint has changed and ADR 0007 must be revisited.
    opened = open_position(demo_core, 2 * btc.min_size)
    deal_id = opened.affected_deals[0].deal_id

    sent = demo_core.api.call(
        "DELETE", "/api/v1/positions", json={"dealId": deal_id, "size": btc.min_size}
    )
    reference = sent.unwrap()["dealReference"]
    confirmation = demo_core.confirmer.confirm(reference).unwrap()
    log.info(
        "partial close confirmation: status=%s affectedDeals=%s",
        confirmation.status,
        confirmation.affected_deals,
    )
    assert [d.status for d in confirmation.affected_deals] == ["FULLY_CLOSED"]

    after = demo_core.api.call("GET", f"/api/v1/positions/{deal_id}")
    assert isinstance(after, Err)
    assert isinstance(after.error, NotFoundError)
    assert after.error.error_code == "error.not-found.dealId"
