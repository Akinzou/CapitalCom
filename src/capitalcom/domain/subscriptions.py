"""The set of keys a stream is subscribed to, and the limits checked before anything is sent."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import ValidationError
from capitalcom.domain.streaming import CandleType

# The demo probe (ADR 0012) refused the 41st quote epic and counted OHLC epics separately.
MAX_QUOTE_EPICS = 40
MAX_OHLC_EPICS = 40

_E = TypeVar("_E", bound=StrEnum)


@dataclass(frozen=True, slots=True)
class OhlcKey:
    """One OHLC subscription: an epic's bars of one resolution and one candle type."""

    epic: str
    resolution: Resolution
    candle_type: CandleType

    def wire(self) -> str:
        """The key the server uses in its answers: ``EPIC:RESOLUTION:type``."""
        return f"{self.epic}:{self.resolution.value}:{self.candle_type.value}"


def _distinct(values: object, field: str) -> list[str]:
    # A bare string is refused because iterating it would subscribe one epic per character;
    # a duplicate is refused rather than dropped, so a caller's typo is not silently hidden.
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise ValidationError(f"{field} must be a list, not {type(values).__name__}")
    items = list(values)
    if not items:
        raise ValidationError(f"{field} must not be empty")
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"{field}: each item must be a non-blank string")
    if len(set(items)) != len(items):
        raise ValidationError(f"{field} must not repeat an item")
    return [str(item) for item in items]


def _epics(values: Iterable[str]) -> list[str]:
    return _distinct(values, "epics")


def _members(values: Iterable[_E | str], field: str, enum: type[_E]) -> list[_E]:
    try:
        members = [enum(v) for v in _distinct(values, field)]
    except ValueError:
        names = ", ".join(m.value for m in enum)
        raise ValidationError(f"{field} must be among {names}") from None
    return members


def _candle(value: CandleType | str) -> CandleType:
    try:
        return CandleType(value)
    except ValueError:
        names = ", ".join(m.value for m in CandleType)
        raise ValidationError(f"candle must be one of {names}, got {value!r}") from None


class Subscriptions:
    """What the stream should be subscribed to, in the order the caller asked for it.

    Every method checks its input before changing anything, so a refused call leaves the set
    as it was.
    """

    def __init__(self) -> None:
        self._quotes: dict[str, None] = {}
        self._ohlc: dict[OhlcKey, None] = {}

    @property
    def quotes(self) -> tuple[str, ...]:
        """Subscribed quote epics."""
        return tuple(self._quotes)

    @property
    def ohlc(self) -> tuple[OhlcKey, ...]:
        """Subscribed OHLC keys."""
        return tuple(self._ohlc)

    def add_quotes(self, epics: Sequence[str]) -> tuple[str, ...]:
        """Add quote epics; return only those not subscribed before."""
        new = [e for e in _epics(epics) if e not in self._quotes]
        if len(self._quotes) + len(new) > MAX_QUOTE_EPICS:
            raise ValidationError(f"at most {MAX_QUOTE_EPICS} quote epics per stream")
        self._quotes.update(dict.fromkeys(new))
        return tuple(new)

    def add_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str],
        candle_type: CandleType | str,
    ) -> tuple[OhlcKey, ...]:
        """Add each epic in each resolution, of one candle type; return only the new keys."""
        wanted_epics = _epics(epics)
        wanted_resolutions = _members(resolutions, "resolutions", Resolution)
        candle = _candle(candle_type)
        new = [
            key
            for epic in wanted_epics
            for resolution in wanted_resolutions
            if (key := OhlcKey(epic, resolution, candle)) not in self._ohlc
        ]
        if len({k.epic for k in self._ohlc} | set(wanted_epics)) > MAX_OHLC_EPICS:
            raise ValidationError(f"at most {MAX_OHLC_EPICS} OHLC epics per stream")
        self._ohlc.update(dict.fromkeys(new))
        return tuple(new)

    def remove_quotes(self, epics: Sequence[str]) -> tuple[str, ...]:
        """Remove quote epics; an epic that is not subscribed raises."""
        gone = _epics(epics)
        unknown = [e for e in gone if e not in self._quotes]
        if unknown:
            raise ValidationError(f"not subscribed to quotes of {', '.join(unknown)}")
        for epic in gone:
            del self._quotes[epic]
        return tuple(gone)

    def remove_ohlc(
        self,
        epics: Sequence[str],
        resolutions: Sequence[Resolution | str] | None,
        candle_types: Sequence[CandleType | str] | None,
    ) -> tuple[OhlcKey, ...]:
        """Remove the matching OHLC keys; ``None`` matches every resolution or candle type.

        An epic with no matching key raises, as unsubscribing it would change nothing.
        """
        gone_epics = _epics(epics)
        res = None if resolutions is None else set(_members(resolutions, "resolutions", Resolution))
        types = None if candle_types is None else set(_members(candle_types, "candles", CandleType))
        gone = [
            k
            for k in self._ohlc
            if k.epic in gone_epics
            and (res is None or k.resolution in res)
            and (types is None or k.candle_type in types)
        ]
        unknown = [e for e in gone_epics if all(k.epic != e for k in gone)]
        if unknown:
            raise ValidationError(f"no matching OHLC subscription for {', '.join(unknown)}")
        for key in gone:
            del self._ohlc[key]
        return tuple(gone)

    def discard(self, keys: Iterable[str]) -> None:
        """Forget keys the server refused, given as it names them; unknown keys are ignored."""
        refused = set(keys)
        for epic in [e for e in self._quotes if e in refused]:
            del self._quotes[epic]
        for key in [k for k in self._ohlc if k.wire() in refused]:
            del self._ohlc[key]
