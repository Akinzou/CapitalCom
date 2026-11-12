"""Stream frames as the probe recorded them (addendum §3), and the reading of acknowledgements."""

import json
from decimal import Decimal

import pytest

from capitalcom.application.result import Err, Ok
from capitalcom.application.session import SessionTokens
from capitalcom.application.stream_frames import (
    Ack,
    Event,
    Unknown,
    check_ack,
    decode_frame,
    encode_frame,
    is_invalid_session,
)
from capitalcom.domain.errors import ResponseFormatError, SubscriptionError, ValidationError
from capitalcom.domain.secret import Secret
from capitalcom.domain.streaming import Quote

CST = "cst-token-value-1234"
XST = "security-token-value-5678"
TOKENS = SessionTokens(Secret(CST), Secret(XST), 1)

QUOTE_FRAME = (
    '{"status": "OK", "destination": "quote", "payload": {"epic": "BTCUSD", "product": "CFD",'
    ' "bid": 73578.2, "bidQty": 0.2, "ofr": 73628.2, "ofrQty": 0.2, "timestamp": 1794446435768}}'
)
SUBSCRIBE_ACK = (
    '{"status": "OK", "destination": "marketData.subscribe", "correlationId": "1",'
    ' "payload": {"subscriptions": {"BTCUSD": "PROCESSED"}}}'
)
LIMIT_ACK = (
    '{"status": "OK", "destination": "marketData.subscribe", "correlationId": "8",'
    ' "payload": {"subscriptions": {"SOYBEANOIL": "ERROR: Max Subscription limit reached."}}}'
)
NULL_EPIC_ACK = (
    '{"status": "ERROR", "destination": "marketData.subscribe", "correlationId": "5",'
    ' "payload": {"subscriptions": {}, "errorCode": "error.null.epic"}}'
)
REFUSED_SESSION_ACK = (
    '{"status": "ERROR", "destination": "ping", "correlationId": "4",'
    ' "payload": {"errorCode": "error.invalid.session.token"}}'
)


def ack_of(text: str) -> Ack:
    frame = decode_frame(text)
    assert isinstance(frame, Ack)
    return frame


def test_encode_subscribe_carries_tokens_and_payload() -> None:
    frame = json.loads(encode_frame("marketData.subscribe", "7", TOKENS, {"epics": ["GOLD"]}))
    assert frame == {
        "destination": "marketData.subscribe",
        "correlationId": "7",
        "cst": CST,
        "securityToken": XST,
        "payload": {"epics": ["GOLD"]},
    }


def test_encode_ping_has_no_payload() -> None:
    frame = json.loads(encode_frame("ping", "2", TOKENS, None))
    assert "payload" not in frame
    assert frame["destination"] == "ping"


def test_frame_repr_and_errors_never_contain_tokens() -> None:
    with pytest.raises(ValidationError) as encoding:
        encode_frame("marketData.subscribe", "1", TOKENS, {"epics": [object()]})
    broken = '{"status": "OK", "cst": "' + CST + '", "securityToken": "' + XST + '"'
    with pytest.raises(ResponseFormatError) as decoding:
        decode_frame(broken)
    echoed = ack_of('{"status": "OK", "correlationId": "1", "cst": "' + CST + '", "payload": {}}')
    for text in (str(encoding.value), str(decoding.value), repr(echoed)):
        assert CST not in text
        assert XST not in text


def test_decode_quote_event() -> None:
    frame = decode_frame(QUOTE_FRAME)
    assert isinstance(frame, Event)
    assert isinstance(frame.value, Quote)
    assert frame.value.bid == Decimal("73578.2")


def test_decode_candle_event() -> None:
    frame = decode_frame(
        '{"status": "OK", "destination": "ohlc.event", "payload": {"resolution": "MINUTE",'
        ' "epic": "BTCUSD", "type": "classic", "priceType": "ask", "t": 1794446400000,'
        ' "h": 2, "l": 1, "o": 1.5, "c": 1.75}}'
    )
    assert isinstance(frame, Event)
    assert frame.value.epic == "BTCUSD"


def test_decode_ack_with_correlation() -> None:
    ack = ack_of(SUBSCRIBE_ACK)
    assert ack.correlation_id == "1"
    assert ack.status == "OK"
    assert ack.payload["subscriptions"] == {"BTCUSD": "PROCESSED"}
    assert ack.error_code is None
    assert ack_of(REFUSED_SESSION_ACK).error_code == "error.invalid.session.token"


def test_unknown_destination_is_unknown() -> None:
    assert decode_frame('{"status": "OK", "destination": "news", "payload": {}}') == Unknown("news")


@pytest.mark.parametrize("text", ["[1, 2]", "not json", '"quote"', "{}"])
def test_non_object_frame_raises_response_format_error(text: str) -> None:
    with pytest.raises(ResponseFormatError):
        decode_frame(text)


def test_event_missing_a_field_raises() -> None:
    with pytest.raises(ResponseFormatError, match="ofrQty"):
        decode_frame(QUOTE_FRAME.replace('"ofrQty"', '"other"'))


def test_check_ack_accepts_processed() -> None:
    assert check_ack(ack_of(SUBSCRIBE_ACK), ["BTCUSD"]) == Ok(None)


def test_check_ack_accepts_already_subscribed() -> None:
    ack = ack_of(SUBSCRIBE_ACK.replace("PROCESSED", "ALREADY_SUBSCRIBED"))
    assert check_ack(ack, ["BTCUSD"]) == Ok(None)


def test_check_ack_accepts_not_subscribed_on_unsubscribe() -> None:
    ack = ack_of(SUBSCRIBE_ACK.replace("PROCESSED", "NOT_SUBSCRIBED"))
    assert check_ack(ack, ["BTCUSD"]) == Ok(None)


def test_check_ack_reports_error_text_per_key() -> None:
    result = check_ack(ack_of(LIMIT_ACK), ["SOYBEANOIL"])
    assert isinstance(result, Err)
    assert result.error.refused == {"SOYBEANOIL": "ERROR: Max Subscription limit reached."}


def test_check_ack_reports_missing_keys_as_MISSING() -> None:  # noqa: N802 - names the value
    # The probe's 41-epic OHLC call answered two epics under their bare names, not their keys.
    ack = ack_of(
        '{"status": "OK", "correlationId": "13", "payload": {"subscriptions": {'
        '"GOLD:MINUTE:classic": "PROCESSED",'
        ' "SOYBEANOIL": "ERROR: Max Subscription limit reached."}}}'
    )
    result = check_ack(ack, ["GOLD:MINUTE:classic", "SOYBEANOIL:MINUTE:classic"])
    assert isinstance(result, Err)
    assert result.error.refused == {
        "SOYBEANOIL": "ERROR: Max Subscription limit reached.",
        "SOYBEANOIL:MINUTE:classic": "MISSING",
    }


def test_check_ack_refuses_an_unexpected_status_for_a_requested_key() -> None:
    result = check_ack(ack_of(SUBSCRIBE_ACK.replace("PROCESSED", "PENDING")), ["BTCUSD"])
    assert isinstance(result, Err)
    assert result.error.refused == {"BTCUSD": "PENDING"}


def test_check_ack_status_error_carries_error_code() -> None:
    result = check_ack(ack_of(NULL_EPIC_ACK), ["GOLD"])
    assert isinstance(result, Err)
    assert isinstance(result.error, SubscriptionError)
    assert result.error.error_code == "error.null.epic"
    assert result.error.refused == {"GOLD": "ERROR: error.null.epic"}


def test_check_ack_of_a_ping_needs_no_keys() -> None:
    ping = ack_of('{"status": "OK", "destination": "ping", "correlationId": "16", "payload": {}}')
    assert check_ack(ping, []) == Ok(None)


def test_is_invalid_session() -> None:
    assert is_invalid_session(ack_of(REFUSED_SESSION_ACK))
    assert not is_invalid_session(ack_of(NULL_EPIC_ACK))
    assert not is_invalid_session(ack_of(SUBSCRIBE_ACK))
