"""Session and account read models."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from capitalcom.domain.parsing import require_decimal, require_str


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """The live session, from ``GET /api/v1/session``."""

    client_id: str
    account_id: str
    timezone_offset: Decimal
    locale: str
    currency: str
    stream_endpoint: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "SessionInfo":
        """Build the session info from the decoded JSON body."""
        return cls(
            client_id=require_str(payload, "clientId"),
            account_id=require_str(payload, "accountId"),
            # Decimal, not int: some zones are offset by half or three quarters of an hour.
            timezone_offset=require_decimal(payload, "timezoneOffset"),
            locale=require_str(payload, "locale"),
            currency=require_str(payload, "currency"),
            stream_endpoint=require_str(payload, "streamEndpoint"),
            raw=payload,
        )
