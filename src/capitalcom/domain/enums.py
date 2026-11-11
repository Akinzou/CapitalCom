"""Enumerations whose values are the strings the Capital.com API uses."""

from enum import Enum, StrEnum


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
