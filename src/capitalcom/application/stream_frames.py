"""Frames of the Capital.com WebSocket protocol: building requests, reading what comes back.

Every request frame carries the session tokens, so frames are never logged and no error
raised here quotes a frame's text.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from capitalcom.application.json_codec import decode_json, encode_json
from capitalcom.application.result import Err, Ok, Result
from capitalcom.application.session import SessionTokens
from capitalcom.domain.errors import SubscriptionError
from capitalcom.domain.parsing import (
    as_mapping,
    format_error,
    optional_str,
    require_mapping,
    require_str,
)
from capitalcom.domain.streaming import Candle, Quote, parse_candle, parse_quote

QUOTES_SUBSCRIBE = "marketData.subscribe"
QUOTES_UNSUBSCRIBE = "marketData.unsubscribe"
OHLC_SUBSCRIBE = "OHLCMarketData.subscribe"
OHLC_UNSUBSCRIBE = "OHLCMarketData.unsubscribe"
PING = "ping"

INVALID_SESSION = "error.invalid.session.token"
MISSING = "MISSING"
# The probe saw PROCESSED and ALREADY_SUBSCRIBED on subscribe and NOT_SUBSCRIBED on
# unsubscribe; each means the key is now in the state the caller asked for. Kept apart, so a
# subscribe answered NOT_SUBSCRIBED is a refusal, not a success with no quotes behind it.
_SUBSCRIBED = frozenset({"PROCESSED", "ALREADY_SUBSCRIBED"})
_UNSUBSCRIBED = frozenset({"PROCESSED", "NOT_SUBSCRIBED"})


@dataclass(frozen=True, slots=True)
class Ack:
    """The server's answer to one request, matched to it by ``correlation_id``."""

    correlation_id: str
    status: str
    payload: Mapping[str, Any] = field(repr=False)
    error_code: str | None


@dataclass(frozen=True, slots=True)
class Event:
    """A pushed price event."""

    value: Quote | Candle


@dataclass(frozen=True, slots=True)
class Unknown:
    """A pushed frame of a kind this version does not read; Capital.com may add kinds."""

    destination: str


Incoming: TypeAlias = Ack | Event | Unknown


def encode_frame(
    destination: str,
    correlation_id: str,
    tokens: SessionTokens,
    payload: Mapping[str, Any] | None,
) -> str:
    """Build one request frame; the result holds the session tokens and must not be logged."""
    frame: dict[str, Any] = {
        "destination": destination,
        "correlationId": correlation_id,
        "cst": tokens.cst.reveal(),
        "securityToken": tokens.security_token.reveal(),
    }
    if payload is not None:
        frame["payload"] = payload
    return encode_json(frame).decode("utf-8")


def decode_frame(text: str) -> Incoming:
    """Read one frame; a frame that is not a JSON object, or a known event with a missing
    field, raises ``ResponseFormatError``."""
    try:
        decoded = decode_json(text.encode("utf-8"))
    except ValueError:
        raise format_error("frame", f"not JSON ({len(text)} characters)") from None
    frame = as_mapping(decoded, "frame")
    if "correlationId" in frame:
        payload = as_mapping(frame.get("payload") or {}, "payload")
        return Ack(
            correlation_id=require_str(frame, "correlationId"),
            status=require_str(frame, "status"),
            payload=payload,
            error_code=optional_str(payload, "errorCode"),
        )
    destination = require_str(frame, "destination")
    if destination == "quote":
        return Event(parse_quote(require_mapping(frame, "payload")))
    if destination == "ohlc.event":
        return Event(parse_candle(require_mapping(frame, "payload")))
    return Unknown(destination)


def check_ack(
    ack: Ack, expected: Sequence[str], *, unsubscribe: bool = False
) -> Result[None, SubscriptionError]:
    """Accept the answer only if every requested key reached the requested state."""
    accepted = _UNSUBSCRIBED if unsubscribe else _SUBSCRIBED
    if ack.status == "ERROR":
        reason = f"ERROR: {ack.error_code or 'no error code'}"
        return Err(SubscriptionError(dict.fromkeys(expected, reason), ack.error_code))
    answered = ack.payload.get("subscriptions")
    keys: Mapping[str, Any] = answered if isinstance(answered, Mapping) else {}
    # A refusal may come back under a different key than the one asked for (the probe saw
    # OHLC refusals under the bare epic), so every ERROR entry is reported as it came.
    refused = {
        str(key): str(text)
        for key, text in keys.items()
        if not isinstance(text, str) or text.startswith("ERROR")
    }
    for key in expected:
        text = keys.get(key)
        if text is None:
            refused[key] = MISSING
        elif text not in accepted:
            refused[key] = str(text)
    return Err(SubscriptionError(refused, ack.error_code)) if refused else Ok(None)


def is_invalid_session(ack: Ack) -> bool:
    """True when the server refused the frame's tokens."""
    return ack.status == "ERROR" and ack.error_code == INVALID_SESSION
