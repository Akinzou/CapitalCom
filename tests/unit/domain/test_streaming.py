"""Streaming events read from the probe's frames, and the stream's own errors and host."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalcom.domain.enums import STREAM_URL, Environment, Resolution
from capitalcom.domain.errors import (
    CapitalComError,
    ResponseFormatError,
    StreamError,
    SubscriptionError,
    TransportError,
)
from capitalcom.domain.streaming import (
    CandleType,
    Gap,
    GapReason,
    PriceSide,
    parse_candle,
    parse_quote,
)

# Payloads recorded by the stage 4 demo probe (addendum §3), decoded with parse_float=Decimal.
QUOTE = {
    "epic": "BTCUSD",
    "product": "CFD",
    "bid": Decimal("73578.2"),
    "bidQty": Decimal("0.2"),
    "ofr": Decimal("73628.2"),
    "ofrQty": Decimal("0.2"),
    "timestamp": 1794446435768,
}
CANDLE = {
    "resolution": "MINUTE",
    "epic": "BTCUSD",
    "type": "classic",
    "priceType": "bid",
    "t": 1794446400000,
    "h": Decimal("73625.45"),
    "l": Decimal("73566.85"),
    "o": Decimal("73625.45"),
    "c": Decimal("73566.95"),
    "lastTradedVolume": 216,
}


def test_parse_quote_probe_sample() -> None:
    quote = parse_quote(QUOTE)
    assert quote.epic == "BTCUSD"
    assert quote.bid == Decimal("73578.2")
    assert quote.bid_size == Decimal("0.2")
    assert quote.offer == Decimal("73628.2")
    assert quote.offer_size == Decimal("0.2")
    assert quote.time == datetime(2026, 11, 12, 1, 20, 35, 768000, tzinfo=UTC)
    assert quote.raw["product"] == "CFD"


def test_parse_quote_missing_offer_raises() -> None:
    with pytest.raises(ResponseFormatError, match="ofr"):
        parse_quote({k: v for k, v in QUOTE.items() if k != "ofr"})


def test_parse_candle_probe_sample() -> None:
    candle = parse_candle(CANDLE)
    assert candle.epic == "BTCUSD"
    assert candle.resolution is Resolution.MINUTE
    assert candle.candle_type is CandleType.CLASSIC
    assert candle.price_side is PriceSide.BID
    assert candle.time == datetime(2026, 11, 12, 1, 20, tzinfo=UTC)
    assert (candle.open, candle.high) == (Decimal("73625.45"), Decimal("73625.45"))
    assert (candle.low, candle.close) == (Decimal("73566.85"), Decimal("73566.95"))
    assert candle.volume == 216


def test_parse_candle_without_volume() -> None:
    candle = parse_candle({k: v for k, v in CANDLE.items() if k != "lastTradedVolume"})
    assert candle.volume is None


def test_parse_candle_unknown_price_type_raises() -> None:
    with pytest.raises(ResponseFormatError, match="priceType"):
        parse_candle({**CANDLE, "priceType": "mid"})


def test_parse_candle_unknown_resolution_raises() -> None:
    with pytest.raises(ResponseFormatError, match="resolution"):
        parse_candle({**CANDLE, "resolution": "SECOND"})


def test_events_hide_raw_from_repr_and_equality() -> None:
    assert "raw" not in repr(parse_quote(QUOTE))
    assert parse_quote(QUOTE) == parse_quote({**QUOTE, "product": "other"})


def test_gap_is_a_plain_value() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    gap = Gap(since, until, GapReason.NETWORK)
    assert gap == Gap(since, until, GapReason.NETWORK)
    assert {r.value for r in GapReason} == {"NETWORK", "SERVER_CLOSED", "ACCOUNT_SWITCHED"}


def test_subscription_error_carries_refused_keys() -> None:
    error = SubscriptionError({"NOPE": "ERROR: NOPE not found", "GOLD": "MISSING"}, None)
    assert isinstance(error, CapitalComError)
    assert error.refused == {"NOPE": "ERROR: NOPE not found", "GOLD": "MISSING"}
    assert error.error_code is None
    assert "NOPE: ERROR: NOPE not found" in str(error)
    coded = SubscriptionError({}, "error.null.epic")
    assert coded.error_code == "error.null.epic"
    assert "error.null.epic" in str(coded)


def test_subscription_error_refused_is_read_only() -> None:
    error = SubscriptionError({"NOPE": "MISSING"}, None)
    with pytest.raises(TypeError):
        error.refused["X"] = "Y"  # type: ignore[index]


def test_stream_error_is_a_transport_error() -> None:
    assert issubclass(StreamError, TransportError)


def test_stream_url_is_pinned_for_both_environments() -> None:
    assert STREAM_URL == "wss://api-streaming-capital.backend-capital.com/connect"
    assert Environment.DEMO.stream_url == STREAM_URL
    assert Environment.LIVE.stream_url == STREAM_URL
