"""The WebSocket stream on demo: the pinned host, one quote and one bar, then a clean close.

Only event types and counts are logged: prices are public, but nothing here should tie a
run's output to the account.
"""

import logging
import time
from collections import Counter

import pytest

from capitalcom.api.client import CapitalCom
from capitalcom.application.session import Credentials
from capitalcom.domain.enums import Environment
from capitalcom.domain.streaming import Candle, Quote
from tests.contract.conftest import EPIC

pytestmark = pytest.mark.contract
log = logging.getLogger("contract")

# A MINUTE bar arrives at the minute boundary (probe P6), so 90 s covers one full minute
# plus connect and subscribe time.
DEADLINE_S = 90.0


def test_stream_round_trip(demo_credentials: Credentials) -> None:
    with CapitalCom(
        demo_credentials.api_key.reveal(),
        demo_credentials.identifier,
        demo_credentials.password.reveal(),
        environment=Environment.DEMO,
    ) as cc:
        reported = cc.session.info().stream_endpoint
        assert reported.rstrip("/") + "/connect" == Environment.DEMO.stream_url
        status = cc.markets.get(EPIC).snapshot.market_status
        if status != "TRADEABLE":
            pytest.skip(f"{EPIC} {status}")
        seen: Counter[str] = Counter()
        with cc.stream.connect() as stream:
            stream.subscribe_quotes([EPIC])
            stream.subscribe_ohlc([EPIC])
            deadline = time.monotonic() + DEADLINE_S
            for event in stream:
                seen[type(event).__name__] += 1
                if seen[Quote.__name__] and seen[Candle.__name__]:
                    break
                if time.monotonic() > deadline:
                    break
            stream.unsubscribe_quotes([EPIC])
            stream.unsubscribe_ohlc([EPIC])
        log.info("stream events by type: %s", dict(seen))
        assert seen[Quote.__name__] >= 1
        assert seen[Candle.__name__] >= 1
