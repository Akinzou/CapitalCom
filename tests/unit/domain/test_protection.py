"""Stop-loss and take-profit values: each combination the server refuses cannot be built."""

from decimal import Decimal

import pytest

from capitalcom.domain.errors import ValidationError
from capitalcom.domain.protection import StopLoss, TakeProfit, protection_body

BAD_NUMBERS = [True, 0.1, Decimal("NaN"), 0, -1, "5"]


def test_a_distance_stop_writes_only_its_key() -> None:
    assert StopLoss(distance=Decimal("5")).to_body() == {"stopDistance": Decimal("5")}


def test_flags_are_written_only_when_set() -> None:
    assert StopLoss(level=1, guaranteed=True).to_body() == {
        "stopLevel": Decimal(1),
        "guaranteedStop": True,
    }
    assert StopLoss(distance=2, trailing=True).to_body() == {
        "stopDistance": Decimal(2),
        "trailingStop": True,
    }


def test_amounts_are_kept_as_decimal() -> None:
    stop = StopLoss(amount=3)
    assert stop.amount == Decimal(3)
    assert isinstance(stop.amount, Decimal)
    assert stop.to_body() == {"stopAmount": Decimal(3)}


@pytest.mark.parametrize(
    "make",
    [
        lambda: StopLoss(),
        lambda: StopLoss(level=1, distance=1),
        lambda: StopLoss(distance=1, amount=1),
        lambda: StopLoss(distance=1, guaranteed=True, trailing=True),
        lambda: StopLoss(level=1, trailing=True),
        lambda: StopLoss(level=1, guaranteed=1),  # type: ignore[arg-type]
        lambda: TakeProfit(),
        lambda: TakeProfit(level=1, amount=1),
    ],
)
def test_combinations_the_server_refuses_raise(make: object) -> None:
    with pytest.raises(ValidationError):
        make()  # type: ignore[operator]


@pytest.mark.parametrize("value", BAD_NUMBERS)
def test_bad_numbers_raise(value: object) -> None:
    with pytest.raises(ValidationError):
        StopLoss(distance=value)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        TakeProfit(amount=value)  # type: ignore[arg-type]


def test_take_profit_writes_its_key() -> None:
    assert TakeProfit(level=Decimal("1.1")).to_body() == {"profitLevel": Decimal("1.1")}
    assert TakeProfit(distance=4).to_body() == {"profitDistance": Decimal(4)}


def test_protection_body_merges_both_sides() -> None:
    assert protection_body(None, None) == {}
    assert protection_body(StopLoss(level=1), TakeProfit(amount=2)) == {
        "stopLevel": Decimal(1),
        "profitAmount": Decimal(2),
    }


def test_protection_body_refuses_other_types() -> None:
    with pytest.raises(ValidationError, match="stop"):
        protection_body({"stopLevel": 1}, None)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="profit"):
        protection_body(None, StopLoss(level=1))  # type: ignore[arg-type]
