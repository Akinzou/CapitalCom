"""Probe: does the undocumented ``DELETE /api/v1/positions`` with a body close part of a position?

1.0.4's ``close_position_by_id(id, size=...)`` relies on it. Stage 3 keeps that path only if this
probe shows a partial close; otherwise the legacy call raises instead of closing everything.
"""

import logging

import pytest

from capitalcom.api.composition import Core
from capitalcom.domain.parsing import to_decimal
from tests.contract.conftest import Market, open_position

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")


def test_legacy_partial_close_endpoint_closes_only_part(demo_core: Core, btc: Market) -> None:
    opened = open_position(demo_core, 2 * btc.min_size)
    deal_id = opened.affected_deals[0].deal_id

    sent = demo_core.api.call(
        "DELETE", "/api/v1/positions", json={"dealId": deal_id, "size": btc.min_size}
    )
    log.info("partial close answer: %r", sent)
    reference = sent.unwrap()["dealReference"]
    confirmation = demo_core.confirmer.confirm(reference).unwrap()
    log.info(
        "partial close confirmation: status=%s affectedDeals=%s",
        confirmation.status,
        confirmation.affected_deals,
    )

    position = demo_core.api.call("GET", f"/api/v1/positions/{deal_id}").unwrap()
    remaining = to_decimal(position["position"]["size"], "size")
    log.info("size after partial close: %s (opened %s)", remaining, 2 * btc.min_size)
    assert remaining == btc.min_size
