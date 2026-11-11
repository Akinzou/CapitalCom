"""Deal confirmation returned by ``GET /api/v1/confirms/{dealReference}``."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from capitalcom.domain.enums import Direction
from capitalcom.domain.parsing import format_error, to_decimal, to_utc


class Outcome(Enum):
    """What a confirmation means for the caller."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


@dataclass(frozen=True, slots=True)
class AffectedDeal:
    """A position or order touched by the deal."""

    deal_id: str
    status: str


@dataclass(frozen=True, slots=True)
class DealConfirmation:
    """Server's final word on a submitted deal."""

    deal_reference: str
    deal_id: str | None = None
    deal_status: str | None = None
    status: str | None = None
    epic: str | None = None
    direction: Direction | None = None
    level: Decimal | None = None
    size: Decimal | None = None
    reason: str | None = None
    affected_deals: tuple[AffectedDeal, ...] = ()
    date: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "DealConfirmation":
        """Build a confirmation from the decoded JSON body."""
        reference = payload.get("dealReference")
        if not isinstance(reference, str) or not reference:
            raise format_error("dealReference", "missing")
        return cls(
            deal_reference=reference,
            deal_id=_optional_str(payload, "dealId"),
            deal_status=_optional_str(payload, "dealStatus"),
            status=_optional_str(payload, "status"),
            epic=_optional_str(payload, "epic"),
            direction=_direction(payload.get("direction")),
            level=_optional_decimal(payload, "level"),
            size=_optional_decimal(payload, "size"),
            # The rejection shape is undocumented; both keys have been seen in IG-style APIs.
            # The stage 1b contract test pins which one Capital.com uses.
            reason=_optional_str(payload, "reason") or _optional_str(payload, "rejectReason"),
            affected_deals=_affected_deals(payload.get("affectedDeals")),
            date=None if payload.get("date") is None else to_utc(payload["date"], "date"),
            raw=payload,
        )

    @property
    def outcome(self) -> Outcome:
        """ACCEPTED, REJECTED or PENDING; an unknown ``dealStatus`` raises instead of guessing.

        An ACCEPTED status with no deal id and no affected deals is treated as PENDING: 1.0.4
        users saw such incomplete confirmations while the deal was still being booked.
        """
        if self.deal_status is None:
            return Outcome.PENDING
        if self.deal_status == "REJECTED":
            return Outcome.REJECTED
        if self.deal_status == "ACCEPTED":
            if self.deal_id is None and not self.affected_deals:
                return Outcome.PENDING
            return Outcome.ACCEPTED
        raise format_error("dealStatus", f"unknown value {self.deal_status!r}")

    @property
    def is_accepted(self) -> bool:
        """True when the deal was booked."""
        return self.outcome is Outcome.ACCEPTED


def _optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise format_error(key, f"expected a string, got {type(value).__name__}")
    return value


def _optional_decimal(payload: Mapping[str, Any], key: str) -> Decimal | None:
    value = payload.get(key)
    return None if value is None else to_decimal(value, key)


def _direction(value: object) -> Direction | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise format_error("direction", f"expected a string, got {type(value).__name__}")
    try:
        return Direction(value)
    except ValueError:
        raise format_error("direction", f"unknown value {value!r}") from None


def _affected_deals(value: object) -> tuple[AffectedDeal, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise format_error("affectedDeals", "expected a list")
    deals: list[AffectedDeal] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise format_error("affectedDeals", "expected objects")
        deal_id = _optional_str(item, "dealId")
        if deal_id is None:
            raise format_error("affectedDeals.dealId", "missing")
        deals.append(AffectedDeal(deal_id, _optional_str(item, "status") or ""))
    return tuple(deals)
