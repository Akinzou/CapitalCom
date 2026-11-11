"""Request rules applied before anything is sent: path segments, comma lists, resolutions."""

from decimal import Decimal

import pytest

from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import ValidationError
from capitalcom.domain.request_values import bounded_int, caller_quantity, comma_list, path_segment


def test_path_segment_percent_encodes_reserved_characters() -> None:
    assert path_segment("A/B?#", "epic") == "A%2FB%3F%23"


def test_path_segment_keeps_a_plain_epic() -> None:
    assert path_segment("EURUSD", "epic") == "EURUSD"


@pytest.mark.parametrize("value", ["", "  ", ".", "..", None, 7])
def test_path_segment_refuses_values_that_would_break_the_path(value: object) -> None:
    with pytest.raises(ValidationError, match="epic"):
        path_segment(value, "epic")


def test_comma_list_deduplicates_keeping_order() -> None:
    assert comma_list(["A", "B", "A"], "epics", max_items=50) == ("A", "B")


def test_comma_list_refuses_a_bare_string() -> None:
    with pytest.raises(ValidationError, match="not a string"):
        comma_list("AB", "epics", max_items=50)


@pytest.mark.parametrize("values", [[], [""], [" "], ["A,B"], [1], ["A", None], [["A"]]])
def test_comma_list_refuses_empty_or_malformed_items(values: list[object]) -> None:
    with pytest.raises(ValidationError, match="epics"):
        comma_list(values, "epics", max_items=50)  # type: ignore[arg-type]


def test_comma_list_enforces_the_item_limit_after_deduplication() -> None:
    assert comma_list(["A"] * 60, "epics", max_items=1) == ("A",)
    with pytest.raises(ValidationError, match="50"):
        comma_list([f"E{i}" for i in range(51)], "epics", max_items=50)


def test_comma_list_without_a_limit_accepts_many_items() -> None:
    assert comma_list([f"E{i}" for i in range(60)], "ids", max_items=None)[-1] == "E59"


def test_bounded_int_returns_a_value_in_range() -> None:
    assert bounded_int(5, "limit", 1, 500) == 5


@pytest.mark.parametrize("value", [True, "5", 0, 501, 5.0])
def test_bounded_int_refuses_bools_non_ints_and_values_out_of_range(value: object) -> None:
    with pytest.raises(ValidationError, match=r"limit must be an int within 1..500"):
        bounded_int(value, "limit", 1, 500)


def test_caller_quantity_lives_with_the_request_rules() -> None:
    assert caller_quantity(3, "size") == Decimal(3)


def test_resolution_is_the_documented_closed_set() -> None:
    assert Resolution("HOUR_4") is Resolution.HOUR_4
    assert [r.value for r in Resolution] == [
        "MINUTE",
        "MINUTE_5",
        "MINUTE_15",
        "MINUTE_30",
        "HOUR",
        "HOUR_4",
        "DAY",
        "WEEK",
    ]
