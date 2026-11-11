"""Details of one market: instrument, dealing rules, snapshot and pip scale."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from capitalcom.domain.errors import ValidationError
from capitalcom.domain.parsing import (
    as_mapping,
    format_error,
    optional_decimal,
    require_bool,
    require_decimal,
    require_int,
    require_mapping,
    require_str,
    to_decimal,
)
from capitalcom.domain.request_values import caller_quantity


@dataclass(frozen=True, slots=True)
class PipScale:
    """Where the pip sits in a market's price, and the smallest price step."""

    position: int
    tick_size: Decimal

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "PipScale":
        """Read ``pipPosition`` and ``tickSize`` from a market row or a prices body."""
        return cls(require_int(payload, "pipPosition"), require_decimal(payload, "tickSize"))

    @property
    def size(self) -> Decimal:
        """Price value of one pip: 0.01 for USDJPY, 0.0001 for EURUSD."""
        return Decimal(1).scaleb(-self.position)

    def to_distance(self, pips: Decimal | int) -> Decimal:
        """Price distance of ``pips`` pips."""
        return caller_quantity(pips, "pips") * self.size


@dataclass(frozen=True, slots=True)
class RuleValue:
    """One dealing-rule limit with its unit.

    Nothing is converted: the price a ``PERCENTAGE`` limit is taken of is not documented, so
    a conversion here would be a guess presented as a fact.
    """

    value: Decimal
    unit: str

    @classmethod
    def from_api(cls, payload: Mapping[str, Any], field: str) -> "RuleValue":
        """Read ``{"unit": ..., "value": ...}`` of the rule named ``field``."""
        unit = payload.get("unit")
        if not isinstance(unit, str):
            raise format_error(f"{field}.unit", f"expected a string, got {type(unit).__name__}")
        return cls(to_decimal(payload.get("value"), f"{field}.value"), unit)


def _rule(payload: Mapping[str, Any], key: str) -> RuleValue:
    return RuleValue.from_api(require_mapping(payload, key), key)


@dataclass(frozen=True, slots=True)
class DealingRules:
    """Size and distance limits of a market, from ``dealingRules``."""

    min_step_distance: RuleValue
    min_deal_size: RuleValue
    max_deal_size: RuleValue
    min_size_increment: RuleValue
    min_guaranteed_stop_distance: RuleValue
    min_stop_or_profit_distance: RuleValue
    max_stop_or_profit_distance: RuleValue
    market_order_preference: str
    trailing_stops_preference: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "DealingRules":
        """Build the rules; all nine keys were present on every demo market."""
        return cls(
            min_step_distance=_rule(payload, "minStepDistance"),
            min_deal_size=_rule(payload, "minDealSize"),
            max_deal_size=_rule(payload, "maxDealSize"),
            min_size_increment=_rule(payload, "minSizeIncrement"),
            min_guaranteed_stop_distance=_rule(payload, "minGuaranteedStopDistance"),
            min_stop_or_profit_distance=_rule(payload, "minStopOrProfitDistance"),
            max_stop_or_profit_distance=_rule(payload, "maxStopOrProfitDistance"),
            market_order_preference=require_str(payload, "marketOrderPreference"),
            trailing_stops_preference=require_str(payload, "trailingStopsPreference"),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class Instrument:
    """What is traded, from ``instrument``; ``pip`` is ``None`` when no pip data was fetched."""

    epic: str
    symbol: str
    name: str
    type: str
    currency: str
    lot_size: Decimal
    margin_factor: Decimal
    margin_factor_unit: str
    guaranteed_stop_allowed: bool
    pip: PipScale | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any], pip: PipScale | None) -> "Instrument":
        """Build the instrument; the details payload itself carries no pip data."""
        return cls(
            epic=require_str(payload, "epic"),
            symbol=require_str(payload, "symbol"),
            name=require_str(payload, "name"),
            type=require_str(payload, "type"),
            currency=require_str(payload, "currency"),
            lot_size=require_decimal(payload, "lotSize"),
            margin_factor=require_decimal(payload, "marginFactor"),
            margin_factor_unit=require_str(payload, "marginFactorUnit"),
            guaranteed_stop_allowed=require_bool(payload, "guaranteedStopAllowed"),
            pip=pip,
            raw=payload,
        )

    def _known_pip(self) -> PipScale:
        if self.pip is None:
            raise ValidationError(
                f"pip scale unknown for {self.epic}: get_many() details carry none, "
                "and get() found no price data"
            )
        return self.pip

    @property
    def pip_size(self) -> Decimal:
        """Price value of one pip; raises ``ValidationError`` when ``pip`` is unknown."""
        return self._known_pip().size

    def pips_to_distance(self, pips: Decimal | int) -> Decimal:
        """Price distance of ``pips`` pips; raises ``ValidationError`` when ``pip`` is unknown."""
        return self._known_pip().to_distance(pips)

    def lots_to_size(self, lots: Decimal | int) -> Decimal:
        """Deal size of ``lots`` lots."""
        return caller_quantity(lots, "lots") * self.lot_size


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Latest quote of a market; quote fields are ``None`` on markets that have none."""

    market_status: str
    bid: Decimal | None
    offer: Decimal | None
    high: Decimal | None
    low: Decimal | None
    net_change: Decimal | None
    percentage_change: Decimal | None
    decimal_places_factor: int
    scaling_factor: int
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "MarketSnapshot":
        """Build the snapshot; ``updateTime`` is local time and stays in ``raw``."""
        return cls(
            market_status=require_str(payload, "marketStatus"),
            bid=optional_decimal(payload, "bid"),
            offer=optional_decimal(payload, "offer"),
            high=optional_decimal(payload, "high"),
            low=optional_decimal(payload, "low"),
            net_change=optional_decimal(payload, "netChange"),
            percentage_change=optional_decimal(payload, "percentageChange"),
            decimal_places_factor=require_int(payload, "decimalPlacesFactor"),
            scaling_factor=require_int(payload, "scalingFactor"),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class MarketDetails:
    """One market, from ``GET /markets/{epic}`` or an item of ``marketDetails``."""

    instrument: Instrument
    dealing_rules: DealingRules
    snapshot: MarketSnapshot
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: object, pip: PipScale | None = None) -> "MarketDetails":
        """Build the details; ``pip`` comes from a separate prices call, if one was made."""
        body = as_mapping(payload, "marketDetails")
        return cls(
            instrument=Instrument.from_api(require_mapping(body, "instrument"), pip),
            dealing_rules=DealingRules.from_api(require_mapping(body, "dealingRules")),
            snapshot=MarketSnapshot.from_api(require_mapping(body, "snapshot")),
            raw=body,
        )
