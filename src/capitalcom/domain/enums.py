"""Enumerations whose values are the strings the Capital.com API uses."""

from enum import Enum, StrEnum

# The demo probe (ADR 0012) found the same streaming host on demo and live. The host is pinned
# rather than read from the session's streamEndpoint, so a changed or injected field can
# never send the session tokens to a host this library did not choose.
STREAM_URL = "wss://api-streaming-capital.backend-capital.com/connect"


class Direction(StrEnum):
    """Trade direction."""

    BUY = "BUY"
    SELL = "SELL"


class Environment(Enum):
    """Capital.com server environment; the value is the REST base URL."""

    DEMO = "https://demo-api-capital.backend-capital.com"
    LIVE = "https://api-capital.backend-capital.com"

    @property
    def rest_url(self) -> str:
        """Base URL of the REST API, without a trailing slash."""
        return str(self.value)

    @property
    def stream_url(self) -> str:
        """URL of the WebSocket stream; one host serves both environments."""
        return STREAM_URL


class Resolution(StrEnum):
    """Bar length of ``GET /prices``; the documented set is closed, so it is an enum."""

    MINUTE = "MINUTE"
    MINUTE_5 = "MINUTE_5"
    MINUTE_15 = "MINUTE_15"
    MINUTE_30 = "MINUTE_30"
    HOUR = "HOUR"
    HOUR_4 = "HOUR_4"
    DAY = "DAY"
    WEEK = "WEEK"


class OrderType(StrEnum):
    """Kind of working order: LIMIT fills at the level or better, STOP once it is reached."""

    LIMIT = "LIMIT"
    STOP = "STOP"
