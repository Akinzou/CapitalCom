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


def _one_of(owner: str, **given: Decimal | int | None) -> tuple[str, Decimal]:
    """Return the one ``given`` value that is set, as a positive ``Decimal``."""
    chosen = [(name, value) for name, value in given.items() if value is not None]
    if len(chosen) != 1:
        names = ", ".join(given)
        raise ValidationError(f"{owner}: give exactly one of {names}")
    name, value = chosen[0]
    return name, positive_quantity(value, f"{owner}.{name}")


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
        name, value = _one_of("stop", level=level, distance=distance, amount=amount)
        for field_name in ("level", "distance", "amount"):
            object.__setattr__(self, field_name, value if field_name == name else None)
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
        if self.level is not None:
            body: dict[str, Any] = {"stopLevel": self.level}
        elif self.distance is not None:
            body = {"stopDistance": self.distance}
        else:
            body = {"stopAmount": self.amount}
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
        name, value = _one_of("profit", level=level, distance=distance, amount=amount)
        for field_name in ("level", "distance", "amount"):
            object.__setattr__(self, field_name, value if field_name == name else None)

    def to_body(self) -> dict[str, Any]:
        """The ``profit*`` key of a request body."""
        if self.level is not None:
            return {"profitLevel": self.level}
        if self.distance is not None:
            return {"profitDistance": self.distance}
        return {"profitAmount": self.amount}


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
