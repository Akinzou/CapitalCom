"""Stop-loss and take-profit of a position or working order.

The server refuses a stop given in two ways at once (``error.conflict.stoploss.types``), a
guaranteed stop combined with a trailing one, and a trailing stop without a distance. Each
of those is refused here when the value is built, so it never reaches the server.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from capitalcom.domain.errors import ValidationError
from capitalcom.domain.request_values import positive_quantity


def _set_one_of(
    target: object,
    owner: str,
    level: Decimal | int | None,
    distance: Decimal | int | None,
    amount: Decimal | int | None,
) -> str:
    """Store the one value given as a positive ``Decimal`` and the others as ``None``.

    Returns the name of the field that was given.
    """
    given = {"level": level, "distance": distance, "amount": amount}
    chosen = [(name, value) for name, value in given.items() if value is not None]
    if len(chosen) != 1:
        raise ValidationError(f"{owner}: give exactly one of level, distance, amount")
    name, value = chosen[0]
    stored = positive_quantity(value, f"{owner}.{name}")
    for field_name in given:
        object.__setattr__(target, field_name, stored if field_name == name else None)
    return name


def _amount_body(
    prefix: str, level: Decimal | None, distance: Decimal | None, amount: Decimal | None
) -> dict[str, Any]:
    """The one ``<prefix>Level``, ``<prefix>Distance`` or ``<prefix>Amount`` key that is set."""
    if level is not None:
        return {f"{prefix}Level": level}
    if distance is not None:
        return {f"{prefix}Distance": distance}
    return {f"{prefix}Amount": amount}


@dataclass(frozen=True, slots=True, init=False)
class StopLoss:
    """A stop given as a price ``level``, a ``distance`` from the price, or a money ``amount``."""

    level: Decimal | None
    distance: Decimal | None
    amount: Decimal | None
    guaranteed: bool
    trailing: bool

    def __init__(
        self,
        level: Decimal | int | None = None,
        distance: Decimal | int | None = None,
        amount: Decimal | int | None = None,
        *,
        guaranteed: bool = False,
        trailing: bool = False,
    ) -> None:
        name = _set_one_of(self, "stop", level, distance, amount)
        if not isinstance(guaranteed, bool) or not isinstance(trailing, bool):
            raise ValidationError("stop: guaranteed and trailing must be bools")
        if guaranteed and trailing:
            raise ValidationError("stop: a guaranteed stop cannot also be trailing")
        if trailing and name != "distance":
            raise ValidationError("stop: a trailing stop needs a distance")
        object.__setattr__(self, "guaranteed", guaranteed)
        object.__setattr__(self, "trailing", trailing)

    def to_body(self) -> dict[str, Any]:
        """The ``stop*`` keys of a request body."""
        body = _amount_body("stop", self.level, self.distance, self.amount)
        # Flags are sent only when set: the documentation says a guaranteed stop "cannot be
        # set" in hedging mode, and an explicit false is not worth finding out about.
        if self.guaranteed:
            body["guaranteedStop"] = True
        if self.trailing:
            body["trailingStop"] = True
        return body


@dataclass(frozen=True, slots=True, init=False)
class TakeProfit:
    """A take-profit given as a price ``level``, a ``distance`` or a money ``amount``."""

    level: Decimal | None
    distance: Decimal | None
    amount: Decimal | None

    def __init__(
        self,
        level: Decimal | int | None = None,
        distance: Decimal | int | None = None,
        amount: Decimal | int | None = None,
    ) -> None:
        _set_one_of(self, "profit", level, distance, amount)

    def to_body(self) -> dict[str, Any]:
        """The ``profit*`` key of a request body."""
        return _amount_body("profit", self.level, self.distance, self.amount)


def protection_body(stop: StopLoss | None, profit: TakeProfit | None) -> dict[str, Any]:
    """Body keys for ``stop`` and ``profit``; ``{}`` when both are ``None``."""
    if stop is not None and not isinstance(stop, StopLoss):
        raise ValidationError(f"stop must be a StopLoss or None, got {stop!r}")
    if profit is not None and not isinstance(profit, TakeProfit):
        raise ValidationError(f"profit must be a TakeProfit or None, got {profit!r}")
    body: dict[str, Any] = {}
    if stop is not None:
        body |= stop.to_body()
    if profit is not None:
        body |= profit.to_body()
    return body
