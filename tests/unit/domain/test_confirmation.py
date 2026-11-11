from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from capitalcom.domain.confirmation import AffectedDeal, DealConfirmation, Outcome
from capitalcom.domain.enums import Direction
from capitalcom.domain.errors import ResponseFormatError
from capitalcom.domain.parsing import to_decimal, to_utc


def documented_sample() -> dict[str, Any]:
    return {
        "date": "2020-09-23T09:43:39.297",
        "status": "OPEN",
        "dealStatus": "ACCEPTED",
        "epic": "EURUSD",
        "dealReference": "o_1",
        "dealId": "d_1",
        "affectedDeals": [{"dealId": "d_1", "status": "OPENED"}],
        "level": Decimal("1.1234"),
        "size": Decimal("1000"),
        "direction": "BUY",
        "guaranteedStop": False,
        "trailingStop": False,
    }


def test_documented_sample_is_accepted() -> None:
    confirmation = DealConfirmation.from_api(documented_sample())
    assert confirmation.outcome is Outcome.ACCEPTED
    assert confirmation.is_accepted
    assert confirmation.level == Decimal("1.1234")
    assert confirmation.size == Decimal("1000")
    assert confirmation.direction is Direction.BUY
    assert confirmation.deal_id == "d_1"
    assert confirmation.affected_deals == (AffectedDeal("d_1", "OPENED"),)
    assert confirmation.date == datetime(2020, 9, 23, 9, 43, 39, 297000, tzinfo=UTC)
    assert confirmation.date is not None
    assert confirmation.date.tzinfo is UTC


def test_raw_payload_is_kept_but_not_in_repr_or_equality() -> None:
    payload = documented_sample()
    confirmation = DealConfirmation.from_api(payload)
    assert confirmation.raw["guaranteedStop"] is False
    assert "guaranteedStop" not in repr(confirmation)


def test_accepted_without_deal_id_or_affected_deals_is_pending() -> None:
    payload = documented_sample()
    del payload["dealId"]
    payload["affectedDeals"] = []
    confirmation = DealConfirmation.from_api(payload)
    assert confirmation.outcome is Outcome.PENDING
    assert not confirmation.is_accepted


def test_missing_deal_status_is_pending() -> None:
    payload = documented_sample()
    del payload["dealStatus"]
    assert DealConfirmation.from_api(payload).outcome is Outcome.PENDING


def test_rejected_keeps_reason() -> None:
    payload = documented_sample()
    payload["dealStatus"] = "REJECTED"
    payload["reason"] = "INSUFFICIENT_FUNDS"
    confirmation = DealConfirmation.from_api(payload)
    assert confirmation.outcome is Outcome.REJECTED
    assert confirmation.reason == "INSUFFICIENT_FUNDS"


def test_reject_reason_falls_back_to_reject_reason_key() -> None:
    payload = documented_sample()
    payload["dealStatus"] = "REJECTED"
    payload["rejectReason"] = "MARKET_CLOSED"
    assert DealConfirmation.from_api(payload).reason == "MARKET_CLOSED"


def test_unknown_deal_status_raises_and_names_it() -> None:
    payload = documented_sample()
    payload["dealStatus"] = "WEIRD"
    confirmation = DealConfirmation.from_api(payload)
    with pytest.raises(ResponseFormatError, match="WEIRD"):
        _ = confirmation.outcome


def test_missing_deal_reference_raises() -> None:
    payload = documented_sample()
    del payload["dealReference"]
    with pytest.raises(ResponseFormatError, match="dealReference"):
        DealConfirmation.from_api(payload)


def test_optional_fields_may_be_absent() -> None:
    confirmation = DealConfirmation.from_api({"dealReference": "o_2"})
    assert confirmation.deal_id is None
    assert confirmation.level is None
    assert confirmation.direction is None
    assert confirmation.date is None
    assert confirmation.affected_deals == ()


def test_to_decimal_accepts_decimal_int_and_str() -> None:
    assert to_decimal(Decimal("1.5"), "x") == Decimal("1.5")
    assert to_decimal(2, "x") == Decimal(2)
    assert to_decimal("0.0010", "x") == Decimal("0.0010")


@pytest.mark.parametrize("value", [1.5, True, None, "abc", [1]])
def test_to_decimal_rejects_other_types(value: object) -> None:
    # A float means the Decimal-preserving decoder was bypassed somewhere upstream.
    with pytest.raises(ResponseFormatError, match="x"):
        to_decimal(value, "x")


def test_to_utc_with_and_without_fraction_and_with_offset() -> None:
    assert to_utc("2020-09-23T09:43:39", "d") == datetime(2020, 9, 23, 9, 43, 39, tzinfo=UTC)
    assert to_utc("2020-09-23T11:43:39+02:00", "d") == datetime(2020, 9, 23, 9, 43, 39, tzinfo=UTC)


def test_to_utc_rejects_garbage() -> None:
    with pytest.raises(ResponseFormatError, match="d"):
        to_utc("yesterday", "d")
