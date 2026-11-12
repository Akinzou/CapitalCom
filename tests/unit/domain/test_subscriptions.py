"""The stream's subscription set: new keys, limits and removals, checked before sending."""

import pytest

from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import ValidationError
from capitalcom.domain.streaming import CandleType
from capitalcom.domain.subscriptions import OhlcKey, Subscriptions

M1, M5 = Resolution.MINUTE, Resolution.MINUTE_5
CLASSIC, HEIKIN = CandleType.CLASSIC, CandleType.HEIKIN_ASHI


def epics(count: int, prefix: str = "E") -> list[str]:
    return [f"{prefix}{n}" for n in range(count)]


def test_ohlc_key_wire_form() -> None:
    assert OhlcKey("BTCUSD", M5, HEIKIN).wire() == "BTCUSD:MINUTE_5:heikin-ashi"


def test_add_quotes_returns_only_new_keys() -> None:
    subs = Subscriptions()
    assert subs.add_quotes(["GOLD", "EURUSD"]) == ("GOLD", "EURUSD")
    assert subs.add_quotes(["EURUSD", "OIL"]) == ("OIL",)
    assert subs.add_quotes(["GOLD"]) == ()
    assert subs.quotes == ("GOLD", "EURUSD", "OIL")


def test_duplicates_do_not_count_twice_toward_the_limit() -> None:
    subs = Subscriptions()
    subs.add_quotes(epics(40))
    assert subs.add_quotes(epics(40)) == ()


def test_41st_quote_epic_raises_and_changes_nothing() -> None:
    subs = Subscriptions()
    subs.add_quotes(epics(39))
    with pytest.raises(ValidationError, match="40"):
        subs.add_quotes(["X", "Y"])
    assert len(subs.quotes) == 39


def test_ohlc_limit_counts_epics_not_keys() -> None:
    subs = Subscriptions()
    added = subs.add_ohlc(epics(40), [M1, M5], CLASSIC)
    assert len(added) == 80
    assert subs.add_ohlc(epics(40), [M1], HEIKIN) != ()
    with pytest.raises(ValidationError, match="40"):
        subs.add_ohlc(["NEW"], [M1], CLASSIC)
    assert len(subs.ohlc) == 120


def test_quote_and_ohlc_limits_are_separate() -> None:
    subs = Subscriptions()
    subs.add_quotes(epics(40))
    assert len(subs.add_ohlc(epics(40, "O"), [M1], CLASSIC)) == 40


@pytest.mark.parametrize("given", [[], ["GOLD", "GOLD"], ["  "], [""], "GOLD", [3]])
def test_empty_duplicate_or_blank_epics_raise(given: object) -> None:
    subs = Subscriptions()
    with pytest.raises(ValidationError, match="epics"):
        subs.add_quotes(given)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="epics"):
        subs.add_ohlc(given, [M1], CLASSIC)  # type: ignore[arg-type]


@pytest.mark.parametrize("resolutions", [[], [M1, M1], ["SECOND"], "MINUTE"])
def test_bad_resolutions_raise(resolutions: object) -> None:
    with pytest.raises(ValidationError, match="resolutions"):
        Subscriptions().add_ohlc(["GOLD"], resolutions, CLASSIC)  # type: ignore[arg-type]


def test_bad_candle_type_raises() -> None:
    with pytest.raises(ValidationError, match="candle"):
        Subscriptions().add_ohlc(["GOLD"], [M1], "renko")


def test_strings_are_accepted_for_resolutions_and_candle_type() -> None:
    added = Subscriptions().add_ohlc(["GOLD"], ["MINUTE_5"], "heikin-ashi")
    assert added == (OhlcKey("GOLD", M5, HEIKIN),)


def test_remove_quotes_returns_removed_keys() -> None:
    subs = Subscriptions()
    subs.add_quotes(["GOLD", "OIL"])
    assert subs.remove_quotes(["GOLD"]) == ("GOLD",)
    assert subs.quotes == ("OIL",)


def test_remove_unsubscribed_epic_raises() -> None:
    subs = Subscriptions()
    subs.add_quotes(["GOLD"])
    subs.add_ohlc(["GOLD"], [M1], CLASSIC)
    with pytest.raises(ValidationError, match="OIL"):
        subs.remove_quotes(["GOLD", "OIL"])
    with pytest.raises(ValidationError, match="OIL"):
        subs.remove_ohlc(["OIL"], None, None)
    with pytest.raises(ValidationError, match="GOLD"):
        subs.remove_ohlc(["GOLD"], [M5], None)
    assert subs.quotes == ("GOLD",)
    assert len(subs.ohlc) == 1


def test_remove_ohlc_none_means_all_resolutions_and_types() -> None:
    subs = Subscriptions()
    subs.add_ohlc(["GOLD", "OIL"], [M1, M5], CLASSIC)
    subs.add_ohlc(["GOLD"], [M1], HEIKIN)
    removed = subs.remove_ohlc(["GOLD"], None, None)
    assert {k.wire() for k in removed} == {
        "GOLD:MINUTE:classic",
        "GOLD:MINUTE_5:classic",
        "GOLD:MINUTE:heikin-ashi",
    }
    assert subs.remove_ohlc(["OIL"], [M5], [CLASSIC]) == (OhlcKey("OIL", M5, CLASSIC),)
    assert subs.ohlc == (OhlcKey("OIL", M1, CLASSIC),)


def test_discard_removes_refused_wire_keys() -> None:
    subs = Subscriptions()
    subs.add_quotes(["GOLD", "OIL"])
    subs.add_ohlc(["GOLD"], [M1], CLASSIC)
    subs.discard(["OIL", "GOLD:MINUTE:classic", "NEVER"])
    assert subs.quotes == ("GOLD",)
    assert subs.ohlc == ()
