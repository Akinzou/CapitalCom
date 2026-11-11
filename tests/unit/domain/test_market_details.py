"""Market details, instrument, dealing rules and pip scale."""

from decimal import Decimal

import pytest

from capitalcom.domain.errors import ResponseFormatError, ValidationError
from capitalcom.domain.market_details import MarketDetails, PipScale, RuleValue
from capitalcom.domain.order_request import OrderRequest
from tests.unit.market_payloads import details


def test_pip_size_follows_the_pip_position() -> None:
    assert PipScale(2, Decimal("0.001")).size == Decimal("0.01")
    assert PipScale(4, Decimal("0.00001")).size == Decimal("0.0001")


def test_pips_become_a_price_distance() -> None:
    assert PipScale(4, Decimal("0.00001")).to_distance(10) == Decimal("0.0010")
    assert PipScale(2, Decimal("0.001")).to_distance(Decimal("1.5")) == Decimal("0.015")


@pytest.mark.parametrize("pips", [True, Decimal("NaN"), Decimal("Infinity"), "10", 1.5])
def test_to_distance_refuses_non_numbers(pips: object) -> None:
    with pytest.raises(ValidationError, match="pips"):
        PipScale(2, Decimal("0.001")).to_distance(pips)  # type: ignore[arg-type]


def test_pip_scale_is_read_from_a_payload() -> None:
    assert PipScale.from_api({"pipPosition": 2, "tickSize": Decimal("0.001")}) == PipScale(
        2, Decimal("0.001")
    )


def test_details_parse_without_pip_data() -> None:
    parsed = MarketDetails.from_api(details())
    assert parsed.instrument.epic == "SILVER"
    assert parsed.instrument.margin_factor == Decimal(10)
    assert parsed.instrument.guaranteed_stop_allowed is True
    assert parsed.instrument.pip is None
    assert parsed.dealing_rules.max_stop_or_profit_distance == RuleValue(Decimal(60), "PERCENTAGE")
    assert parsed.dealing_rules.min_deal_size == RuleValue(Decimal(1), "POINTS")
    assert parsed.dealing_rules.trailing_stops_preference == "NOT_AVAILABLE"
    assert parsed.snapshot.bid == Decimal("22.041")
    assert parsed.snapshot.decimal_places_factor == 3
    assert parsed.raw["snapshot"]["updateTime"] == "2022-04-06T11:23:00.955"


def test_pip_size_without_pip_data_names_the_epic() -> None:
    instrument = MarketDetails.from_api(details()).instrument
    with pytest.raises(ValidationError, match="pip scale unknown for SILVER"):
        _ = instrument.pip_size
    with pytest.raises(ValidationError, match="pip scale unknown for SILVER"):
        instrument.pips_to_distance(10)


def test_pip_data_given_to_details_reaches_the_instrument() -> None:
    instrument = MarketDetails.from_api(details(), PipScale(2, Decimal("0.001"))).instrument
    assert instrument.pip_size == Decimal("0.01")
    assert instrument.pips_to_distance(5) == Decimal("0.05")


def test_a_missing_dealing_rule_is_named() -> None:
    payload = details()
    del payload["dealingRules"]["minDealSize"]
    with pytest.raises(ResponseFormatError, match="minDealSize"):
        MarketDetails.from_api(payload)


def test_a_rule_without_a_unit_is_named() -> None:
    payload = details()
    del payload["dealingRules"]["maxDealSize"]["unit"]
    with pytest.raises(ResponseFormatError, match=r"maxDealSize\.unit"):
        MarketDetails.from_api(payload)


def test_a_quote_less_snapshot_parses_with_none() -> None:
    payload = details()
    for key in ("bid", "offer", "high", "low", "netChange", "percentageChange", "updateTime"):
        del payload["snapshot"][key]
    snapshot = MarketDetails.from_api(payload).snapshot
    assert (snapshot.bid, snapshot.offer, snapshot.high, snapshot.low) == (None,) * 4
    assert (snapshot.net_change, snapshot.percentage_change) == (None, None)


def test_lots_become_a_size() -> None:
    instrument = MarketDetails.from_api(details()).instrument
    assert instrument.lots_to_size(Decimal("2.5")) == Decimal("2.5")
    with pytest.raises(ValidationError, match="lots"):
        instrument.lots_to_size(True)


def btc_details(**rules: dict[str, object]) -> MarketDetails:
    payload = details("BTCUSD")
    payload["dealingRules"] |= {
        "minDealSize": {"unit": "POINTS", "value": Decimal("0.0001")},
        "maxDealSize": {"unit": "POINTS", "value": Decimal(50)},
        "minSizeIncrement": {"unit": "POINTS", "value": Decimal("0.0001")},
    } | rules
    return MarketDetails.from_api(payload)


def btc_order(size: str) -> OrderRequest:
    return OrderRequest("BTCUSD", "BUY", Decimal(size))


@pytest.mark.parametrize("size", ["0.00005", "51", "0.00015"])
def test_validate_refuses_sizes_outside_the_dealing_rules(size: str) -> None:
    with pytest.raises(ValidationError, match="size"):
        btc_details().validate(btc_order(size))


def test_validate_passes_a_size_on_the_increment_grid() -> None:
    btc_details().validate(btc_order("0.0002"))  # does not raise
    btc_details().dealing_rules.validate(btc_order("50"))  # does not raise


def test_validate_refuses_to_guess_a_rule_in_another_unit() -> None:
    rules = {"minDealSize": {"unit": "PERCENTAGE", "value": Decimal("0.0001")}}
    with pytest.raises(ValidationError, match="cannot check size: minDealSize is in PERCENTAGE"):
        btc_details(**rules).validate(btc_order("0.0002"))


def test_validate_refuses_an_order_for_another_market() -> None:
    with pytest.raises(ValidationError, match="EURUSD"):
        MarketDetails.from_api(details()).validate(OrderRequest("EURUSD", "BUY", 1))
