"""History read models and query parameters."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from capitalcom.domain.errors import ResponseFormatError, ValidationError
from capitalcom.domain.history import Activity, Transaction, history_params

DAY = timedelta(days=1)
T0 = datetime(2022, 4, 1, tzinfo=UTC)
ACTIVITY = {
    "date": "2022-04-01T12:00:00.000",
    "dateUTC": "2022-04-01T10:00:00.000",
    "epic": "SILVER",
    "dealId": "000a0b1c-0001-0002-0003-000000000001",
    "source": "USER",
    "type": "POSITION",
    "status": "ACCEPTED",
}
TRANSACTION = {
    "date": "2022-04-01T12:00:00",
    "dateUtc": "2022-04-01T10:00:00",
    "instrumentName": "Silver",
    "transactionType": "TRADE",
    "note": "Trade closed",
    "reference": "ABC123",
    "size": "-1.50",
    "currency": "USD",
    "status": "PROCESSED",
}


def test_activity_parses_utc_date() -> None:
    activity = Activity.from_api(ACTIVITY)
    assert activity.date == datetime(2022, 4, 1, 10, tzinfo=UTC)
    assert activity.deal_id == ACTIVITY["dealId"]
    assert activity.epic == "SILVER"


def test_unknown_activity_source_is_kept() -> None:
    activity = Activity.from_api({**ACTIVITY, "source": "ROBOT", "epic": None})
    assert activity.source == "ROBOT"
    assert activity.epic is None


def test_transaction_size_string_becomes_decimal() -> None:
    transaction = Transaction.from_api(TRANSACTION)
    assert transaction.size == Decimal("-1.50")
    assert transaction.date == datetime(2022, 4, 1, 10, tzinfo=UTC)
    assert transaction.instrument_name == "Silver"


def test_transaction_without_utc_date_is_rejected() -> None:
    with pytest.raises(ResponseFormatError, match="dateUtc"):
        Transaction.from_api({**TRANSACTION, "dateUtc": None})


def test_params_send_utc_range() -> None:
    start = datetime(2022, 4, 1, 3, 1, tzinfo=timezone(timedelta(hours=2)))
    params = history_params(start, start + timedelta(hours=1), None, max_span=DAY)
    assert params == {"from": "2022-04-01T01:01:00", "to": "2022-04-01T02:01:00"}


def test_params_send_last_period_in_seconds() -> None:
    assert history_params(None, None, timedelta(hours=1), max_span=DAY) == {"lastPeriod": "3600"}
    assert history_params(None, None, None, max_span=DAY) == {}


@pytest.mark.parametrize(
    ("start", "end", "last_period"),
    [
        (T0, None, timedelta(hours=1)),
        (None, T0, timedelta(hours=1)),
        (None, None, timedelta(milliseconds=500)),
        (None, None, timedelta(seconds=1.5)),
        (None, None, DAY + timedelta(seconds=1)),
        (T0 + timedelta(hours=1), T0, None),
        (T0, T0 + DAY + timedelta(seconds=1), None),
        (datetime(2022, 4, 1), None, None),  # noqa: DTZ001 - the naive value is the case
        (T0, datetime(2022, 4, 2), None),  # noqa: DTZ001 - the naive value is the case
    ],
)
def test_invalid_ranges_raise(
    start: datetime | None, end: datetime | None, last_period: timedelta | None
) -> None:
    with pytest.raises(ValidationError):
        history_params(start, end, last_period, max_span=DAY)


def test_without_max_span_long_ranges_pass() -> None:
    params = history_params(T0, T0 + timedelta(days=30), None, max_span=None)
    assert params["to"] == "2022-05-01T00:00:00"
    assert history_params(None, None, timedelta(days=30), max_span=None) == {
        "lastPeriod": "2592000"
    }
