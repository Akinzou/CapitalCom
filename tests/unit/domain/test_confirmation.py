import pickle
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from capitalcom.domain.confirmation import (
    AffectedDeal,
    DealConfirmation,
    Outcome,
    SizeAdjustedError,
)
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


@pytest.mark.parametrize("direction", [1, "UP"])
def test_bad_direction_raises(direction: object) -> None:
    payload = documented_sample()
    payload["direction"] = direction
    with pytest.raises(ResponseFormatError, match="direction"):
        DealConfirmation.from_api(payload)


def observed(status: str, affected: list[tuple[str, str]], **extra: Any) -> DealConfirmation:
    """A confirmation shaped like the ones seen on demo (ADR 0010)."""
    payload: dict[str, Any] = {
        "dealReference": "o_1",
        "dealId": "D1",
        "dealStatus": "ACCEPTED",
        "status": status,
        "size": Decimal("0.00010"),
        "affectedDeals": [{"dealId": deal, "status": state} for deal, state in affected],
    }
    return DealConfirmation.from_api(payload | extra)


def test_position_id_is_the_deal_that_opened() -> None:
    opened = observed("OPEN", [("P1", "OPENED")])
    assert (opened.position_id, opened.deal_id) == ("P1", "D1")


def test_position_id_is_none_when_nothing_opened() -> None:
    assert observed("CLOSED", [("P0", "FULLY_CLOSED")]).position_id is None
    rejected = observed("DELETED", [], dealStatus="REJECTED", rejectReason="RC_NOT_ENOUGH_MARGIN")
    assert rejected.position_id is None
    assert rejected.reason == "RC_NOT_ENOUGH_MARGIN"


def test_require_size_passes_the_size_that_was_booked() -> None:
    opened = observed("OPEN", [("P1", "OPENED")])
    assert opened.require_size(Decimal("0.0001")) is opened


def test_require_size_raises_with_the_confirmation_when_the_server_rounded() -> None:
    opened = observed("OPEN", [("P1", "OPENED")])
    with pytest.raises(SizeAdjustedError) as caught:
        opened.require_size(Decimal("0.00015"))
    assert caught.value.confirmation.position_id == "P1"
    assert caught.value.requested == Decimal("0.00015")
    assert "o_1" in str(caught.value)
    assert "0.00015" in str(caught.value)
    assert "0.00010" in str(caught.value)


def test_require_size_raises_when_no_size_was_reported() -> None:
    opened = observed("OPEN", [("P1", "OPENED")], size=None)
    with pytest.raises(SizeAdjustedError):
        opened.require_size(Decimal("0.0001"))


def test_size_adjusted_error_survives_pickling() -> None:
    error = SizeAdjustedError(Decimal("2"), observed("OPEN", [("P1", "OPENED")]))
    # Round-trips an object this test just built; no external data is ever unpickled.
    copy = pickle.loads(pickle.dumps(error))  # noqa: S301
    assert (copy.requested, copy.confirmation.position_id) == (Decimal("2"), "P1")


def test_size_adjusted_message_names_a_missing_size_and_claims_no_open_position() -> None:
    missing = SizeAdjustedError(Decimal(1), observed("OPEN", [("W1", "OPENED")], size=None))
    assert "no booked size" in str(missing)
    netted = SizeAdjustedError(Decimal(1), observed("CLOSED", [("P0", "FULLY_CLOSED")]))
    for error in (missing, netted):
        assert "is open" not in str(error)
        assert "was booked" in str(error)
