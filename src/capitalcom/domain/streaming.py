"""Events pushed by the Capital.com WebSocket stream: quotes, OHLC bars and gaps."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, TypeVar

from capitalcom.domain.enums import Resolution
from capitalcom.domain.parsing import (
    epoch_ms_to_utc,
    format_error,
    require_decimal,
    require_str,
    to_int,
)


class CandleType(StrEnum):
    """How the server builds an OHLC bar."""

    CLASSIC = "classic"
    HEIKIN_ASHI = "heikin-ashi"


class PriceSide(StrEnum):
    """Side of the book an OHLC bar was built from; the server sends one bar per side."""

    BID = "bid"
    ASK = "ask"


class GapReason(StrEnum):
    """Why the stream was interrupted."""

    NETWORK = "NETWORK"
    SERVER_CLOSED = "SERVER_CLOSED"
    ACCOUNT_SWITCHED = "ACCOUNT_SWITCHED"


@dataclass(frozen=True, slots=True)
class Quote:
    """Best bid and offer of one epic at ``time``."""

    epic: str
    bid: Decimal
    bid_size: Decimal
    offer: Decimal
    offer_size: Decimal
    time: datetime
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class Candle:
    """One OHLC bar of one side; ``time`` is the bar's UTC start.

    The server says nothing about whether the bar is final, so there is no "closed" flag: a
    bar may arrive again with the same ``time`` and new values.
    """

    epic: str
    resolution: Resolution
    candle_type: CandleType
    price_side: PriceSide
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class Gap:
    """The stream delivered nothing between ``since`` and ``until``; events may be missing."""

    since: datetime
    until: datetime
    reason: GapReason


_E = TypeVar("_E", bound=StrEnum)


def _member(payload: Mapping[str, Any], key: str, enum: type[_E]) -> _E:
    value = require_str(payload, key)
    try:
        return enum(value)
    except ValueError:
        raise format_error(key, f"unknown value {value!r}") from None


def parse_quote(payload: Mapping[str, Any]) -> Quote:
    """Build a ``Quote`` from the payload of a ``quote`` event."""
    return Quote(
        epic=require_str(payload, "epic"),
        bid=require_decimal(payload, "bid"),
        bid_size=require_decimal(payload, "bidQty"),
        offer=require_decimal(payload, "ofr"),
        offer_size=require_decimal(payload, "ofrQty"),
        time=epoch_ms_to_utc(payload.get("timestamp"), "timestamp"),
        raw=payload,
    )


def parse_candle(payload: Mapping[str, Any]) -> Candle:
    """Build a ``Candle`` from the payload of an ``ohlc.event``."""
    volume = payload.get("lastTradedVolume")
    return Candle(
        epic=require_str(payload, "epic"),
        resolution=_member(payload, "resolution", Resolution),
        candle_type=_member(payload, "type", CandleType),
        price_side=_member(payload, "priceType", PriceSide),
        time=epoch_ms_to_utc(payload.get("t"), "t"),
        open=require_decimal(payload, "o"),
        high=require_decimal(payload, "h"),
        low=require_decimal(payload, "l"),
        close=require_decimal(payload, "c"),
        volume=None if volume is None else to_int(volume, "lastTradedVolume"),
        raw=payload,
    )
