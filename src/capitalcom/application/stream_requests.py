"""The frames that change a stream's subscriptions, built from the subscription set.

Each builder updates the set first, so a request is only built for a change that passed the
local checks.
"""

from collections.abc import Sequence
from typing import Any, TypeAlias

from capitalcom.application.stream_frames import (
    OHLC_SUBSCRIBE,
    OHLC_UNSUBSCRIBE,
    QUOTES_SUBSCRIBE,
    QUOTES_UNSUBSCRIBE,
)
from capitalcom.domain.enums import Resolution
from capitalcom.domain.streaming import CandleType
from capitalcom.domain.subscriptions import OhlcKey, Subscriptions

# A request is (destination, payload, keys the ack must cover).
Request: TypeAlias = tuple[str, dict[str, Any], list[str]]
# A change is a request plus whether its keys were added to the set.
Change: TypeAlias = tuple[str, dict[str, Any], list[str], bool]

_ORDER = {resolution: index for index, resolution in enumerate(Resolution)}


def subscribe_quotes(subs: Subscriptions, epics: Sequence[str]) -> Change | None:
    """Add quote epics; ``None`` when all of them were subscribed already."""
    new = list(subs.add_quotes(epics))
    return (QUOTES_SUBSCRIBE, {"epics": new}, new, True) if new else None


def unsubscribe_quotes(subs: Subscriptions, epics: Sequence[str]) -> Change:
    """Remove quote epics."""
    gone = list(subs.remove_quotes(epics))
    return (QUOTES_UNSUBSCRIBE, {"epics": gone}, gone, False)


def subscribe_ohlc(
    subs: Subscriptions,
    epics: Sequence[str],
    resolutions: Sequence[Resolution | str],
    candle_type: CandleType | str,
) -> Change | None:
    """Add OHLC keys; ``None`` when all of them were subscribed already."""
    new = subs.add_ohlc(epics, resolutions, candle_type)
    if not new:
        return None
    # Every key this payload implies is in the set: the epics and resolutions come from the
    # new keys, which are a subset of the caller's epics x resolutions.
    payload = {
        "epics": list(dict.fromkeys(k.epic for k in new)),
        "resolutions": [r.value for r in dict.fromkeys(k.resolution for k in new)],
        "type": new[0].candle_type.value,
    }
    return (OHLC_SUBSCRIBE, payload, [k.wire() for k in new], True)


def unsubscribe_ohlc(
    subs: Subscriptions,
    epics: Sequence[str],
    resolutions: Sequence[Resolution | str] | None,
    candle_types: Sequence[CandleType | str] | None,
) -> Change:
    """Remove OHLC keys; a ``None`` filter is left out, which the server reads as "all"."""
    gone = subs.remove_ohlc(epics, resolutions, candle_types)
    payload: dict[str, Any] = {"epics": list(dict.fromkeys(k.epic for k in gone))}
    if resolutions is not None:
        payload["resolutions"] = [Resolution(r).value for r in resolutions]
    if candle_types is not None:
        payload["types"] = [CandleType(t).value for t in candle_types]
    return (OHLC_UNSUBSCRIBE, payload, [k.wire() for k in gone], False)


def resubscribe_requests(subs: Subscriptions) -> list[Request]:
    """Requests that rebuild the whole set on a new connection."""
    quotes = list(subs.quotes)
    requests: list[Request] = []
    if quotes:
        requests.append((QUOTES_SUBSCRIBE, {"epics": quotes}, quotes))
    by_epic: dict[tuple[str, CandleType], list[Resolution]] = {}
    for key in subs.ohlc:
        by_epic.setdefault((key.epic, key.candle_type), []).append(key.resolution)
    # One frame per exact resolution set and candle type: a frame for epics x resolutions
    # would also subscribe pairs the caller has removed.
    groups: dict[tuple[tuple[Resolution, ...], CandleType], list[str]] = {}
    for (epic, candle), found in by_epic.items():
        ordered = tuple(sorted(found, key=_ORDER.__getitem__))
        groups.setdefault((ordered, candle), []).append(epic)
    for (resolutions, candle), epics in groups.items():
        payload = {
            "epics": epics,
            "resolutions": [r.value for r in resolutions],
            "type": candle.value,
        }
        keys = [OhlcKey(e, r, candle).wire() for e in epics for r in resolutions]
        requests.append((OHLC_SUBSCRIBE, payload, keys))
    return requests
