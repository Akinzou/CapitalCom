"""Shared strict converters and query-time formatting."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from capitalcom.domain.api_time import to_api_time
from capitalcom.domain.errors import ResponseFormatError, ValidationError
from capitalcom.domain.parsing import (
    epoch_ms_to_utc,
    optional_decimal,
    optional_str,
    optional_utc,
    require_bool,
    require_decimal,
    require_int,
    require_list,
    require_mapping,
    require_str,
    require_utc,
)


def test_require_str_rejects_a_number_and_names_the_field() -> None:
    with pytest.raises(ResponseFormatError, match="'a'"):
        require_str({"a": 1}, "a")


def test_require_str_rejects_a_missing_key() -> None:
    with pytest.raises(ResponseFormatError, match="'a'"):
        require_str({}, "a")


def test_optional_str_maps_missing_and_null_to_none() -> None:
    assert optional_str({}, "a") is None
    assert optional_str({"a": None}, "a") is None
    assert optional_str({"a": "x"}, "a") == "x"


def test_decimal_converters() -> None:
    assert require_decimal({"n": "1.50"}, "n") == Decimal("1.50")
    assert optional_decimal({}, "n") is None
    with pytest.raises(ResponseFormatError):
        require_decimal({}, "n")


def test_require_bool_rejects_non_bool() -> None:
    assert require_bool({"b": False}, "b") is False
    with pytest.raises(ResponseFormatError, match="'b'"):
        require_bool({"b": 0}, "b")


@pytest.mark.parametrize("value", [Decimal("2.5"), True, "3", None])
def test_require_int_rejects_non_integral_values(value: object) -> None:
    with pytest.raises(ResponseFormatError, match="'n'"):
        require_int({"n": value}, "n")


def test_require_int_accepts_integral_decimal_and_int() -> None:
    assert require_int({"n": Decimal("20")}, "n") == 20
    assert require_int({"n": 7}, "n") == 7


def test_container_converters() -> None:
    assert require_list({"l": [1]}, "l") == [1]
    assert require_mapping({"m": {"k": 1}}, "m") == {"k": 1}
    with pytest.raises(ResponseFormatError, match="'l'"):
        require_list({"l": {}}, "l")
    with pytest.raises(ResponseFormatError, match="'m'"):
        require_mapping({"m": []}, "m")


def test_utc_converters() -> None:
    expected = datetime(2022, 3, 16, 14, 22, 8, tzinfo=UTC)
    assert require_utc({"d": "2022-03-16T14:22:08"}, "d") == expected
    assert optional_utc({}, "d") is None
    with pytest.raises(ResponseFormatError, match="'d'"):
        require_utc({"d": 5}, "d")


def test_epoch_ms_to_utc_is_exact_to_the_millisecond() -> None:
    expected = datetime(2022, 3, 16, 14, 22, 8, 194000, tzinfo=UTC)
    assert epoch_ms_to_utc(1647440528194, "t") == expected
    assert epoch_ms_to_utc(Decimal("1647440528194"), "t") == expected


@pytest.mark.parametrize("value", [Decimal("1.5"), True, "1647440528194"])
def test_epoch_ms_to_utc_rejects_non_integral_values(value: object) -> None:
    with pytest.raises(ResponseFormatError, match="'t'"):
        epoch_ms_to_utc(value, "t")


def test_to_api_time_sends_utc_without_offset() -> None:
    value = datetime(2022, 4, 1, 3, 1, tzinfo=timezone(timedelta(hours=2)))
    assert to_api_time(value, "start") == "2022-04-01T01:01:00"


def test_to_api_time_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="start: datetime must be timezone-aware"):
        to_api_time(datetime(2022, 4, 1), "start")  # noqa: DTZ001 - the naive value is the case
