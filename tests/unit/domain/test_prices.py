"""Price bars and the rules for ``GET /prices`` parameters."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import ResponseFormatError, ValidationError
from capitalcom.domain.prices import BidAsk, PriceBar, price_params

FIRST_BAR = {
    "snapshotTime": "2022-04-06T15:18:00",
    "snapshotTimeUTC": "2022-04-06T13:18:00",
    "openPrice": {"bid": Decimal("24.356"), "ask": Decimal("24.376")},
    "closePrice": {"bid": Decimal("24.378"), "ask": Decimal("24.398")},
    "highPrice": {"bid": Decimal("24.378"), "ask": Decimal("24.398")},
    "lowPrice": {"bid": Decimal("24.355"), "ask": Decimal("24.375")},
    "lastTradedVolume": 187,
}
START = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
END = datetime(2024, 1, 3, tzinfo=UTC)


def test_a_bar_is_read_in_utc_with_bid_and_ask() -> None:
    bar = PriceBar.from_api(FIRST_BAR)
    assert bar.time == datetime(2022, 4, 6, 13, 18, tzinfo=UTC)
    assert bar.open == BidAsk(Decimal("24.356"), Decimal("24.376"))
    assert bar.low.ask == Decimal("24.375")
    assert bar.volume == Decimal(187)
    assert bar.raw["snapshotTime"] == "2022-04-06T15:18:00"


def test_a_bar_without_a_close_ask_is_refused() -> None:
    bar = {**FIRST_BAR, "closePrice": {"bid": Decimal(1)}}
    with pytest.raises(ResponseFormatError, match="ask"):
        PriceBar.from_api(bar)


def test_params_carry_only_what_was_given() -> None:
    assert price_params("HOUR_4", 5, START, END) == {
        "resolution": "HOUR_4",
        "max": "5",
        "from": "2024-01-02T03:04:05",
        "to": "2024-01-03T00:00:00",
    }
    assert price_params(Resolution.DAY, None, None, None) == {"resolution": "DAY"}
    assert price_params(None, None, None, None) == {}


@pytest.mark.parametrize(
    ("resolution", "limit", "start", "end", "match"),
    [
        (None, 0, None, None, "limit"),
        (None, 1001, None, None, "limit"),
        (None, True, None, None, "limit"),
        ("HOURLY", None, None, None, "resolution"),
        (None, None, datetime(2024, 1, 1), None, "timezone"),  # noqa: DTZ001 - naive on purpose
        (None, None, END, START, "start"),
    ],
)
def test_params_refuse_values_the_server_rejects(
    resolution: object, limit: object, start: datetime | None, end: datetime | None, match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        price_params(resolution, limit, start, end)  # type: ignore[arg-type]
