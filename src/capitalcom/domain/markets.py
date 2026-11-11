"""Market rows (search, listing, navigation, watchlists) and the navigation tree."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from capitalcom.domain.market_details import PipScale
from capitalcom.domain.parsing import (
    as_mapping,
    optional_decimal,
    optional_utc,
    require_decimal,
    require_list,
    require_str,
)


@dataclass(frozen=True, slots=True)
class Market:
    """One market row.

    Quote fields and ``update_time_utc`` are ``None`` on the few markets without a quote; a
    listing of every market must not fail because of one of them.
    """

    epic: str
    symbol: str
    instrument_name: str
    instrument_type: str
    market_status: str
    lot_size: Decimal
    pip: PipScale
    bid: Decimal | None
    offer: Decimal | None
    high: Decimal | None
    low: Decimal | None
    update_time_utc: datetime | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Market":
        """Build a market from one row."""
        return cls(
            epic=require_str(payload, "epic"),
            symbol=require_str(payload, "symbol"),
            instrument_name=require_str(payload, "instrumentName"),
            instrument_type=require_str(payload, "instrumentType"),
            market_status=require_str(payload, "marketStatus"),
            lot_size=require_decimal(payload, "lotSize"),
            pip=PipScale.from_api(payload),
            bid=optional_decimal(payload, "bid"),
            offer=optional_decimal(payload, "offer"),
            high=optional_decimal(payload, "high"),
            low=optional_decimal(payload, "low"),
            update_time_utc=optional_utc(payload, "updateTimeUTC"),
            raw=payload,
        )

    def pips_to_distance(self, pips: Decimal | int) -> Decimal:
        """Price distance of ``pips`` pips on this market."""
        return self.pip.to_distance(pips)


def markets_from(payload: Mapping[str, Any], key: str) -> tuple[Market, ...]:
    """Parse the market rows listed under ``key``."""
    return tuple(
        Market.from_api(as_mapping(item, f"{key}[]")) for item in require_list(payload, key)
    )


@dataclass(frozen=True, slots=True)
class MarketNode:
    """One node of the market navigation tree."""

    node_id: str
    name: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "MarketNode":
        """Build a node from ``{"id": ..., "name": ...}``."""
        return cls(require_str(payload, "id"), require_str(payload, "name"), raw=payload)


def nodes_from(payload: Mapping[str, Any]) -> tuple[MarketNode, ...]:
    """Parse the child nodes listed under ``nodes``."""
    return tuple(
        MarketNode.from_api(as_mapping(item, "nodes[]")) for item in require_list(payload, "nodes")
    )


@dataclass(frozen=True, slots=True)
class NodeContents:
    """Children of a navigation node: sub-nodes of a category, or the markets of a leaf."""

    nodes: tuple[MarketNode, ...]
    markets: tuple[Market, ...]
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: object) -> "NodeContents":
        """Build the contents; a category answers without a ``markets`` key."""
        body = as_mapping(payload, "marketnavigation")
        markets = () if body.get("markets") is None else markets_from(body, "markets")
        return cls(nodes=nodes_from(body), markets=markets, raw=body)
