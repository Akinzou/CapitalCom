"""Deal confirmation returned by ``GET /api/v1/confirms/{dealReference}``."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from capitalcom.domain.enums import Direction
from capitalcom.domain.errors import CapitalComError
from capitalcom.domain.parsing import format_error, optional_decimal, optional_str, optional_utc


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
            deal_id=optional_str(payload, "dealId"),
            deal_status=optional_str(payload, "dealStatus"),
            status=optional_str(payload, "status"),
            epic=optional_str(payload, "epic"),
            direction=_direction(payload.get("direction")),
            level=optional_decimal(payload, "level"),
            size=optional_decimal(payload, "size"),
            # The demo server sends rejectReason (RC_NOT_ENOUGH_MARGIN, ADR 0007); reason is
            # still read first in case another environment uses the IG-style key.
            reason=optional_str(payload, "reason") or optional_str(payload, "rejectReason"),
            affected_deals=_affected_deals(payload.get("affectedDeals")),
            date=optional_utc(payload, "date"),
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

    @property
    def position_id(self) -> str | None:
        """Id of the position or working order this deal opened, or ``None``.

        It is the first affected deal with status ``OPENED``; the top-level ``deal_id`` of an
        opened position is not the position (ADR 0007). ``None`` when nothing opened, for
        example when an opposite deal closed a position instead (netting).
        """
        for deal in self.affected_deals:
            if deal.status == "OPENED":
                return deal.deal_id
        return None

    def require_size(self, requested: Decimal) -> "DealConfirmation":
        """Return this confirmation if it booked ``requested``; otherwise raise.

        The server rounds a size that is off its increment grid without saying so, so a
        deal for 0.00015 can come back as 0.00010. The deal exists either way, which is why
        the error carries this confirmation.
        """
        if self.size != requested:
            raise SizeAdjustedError(requested, self)
        return self


class SizeAdjustedError(CapitalComError):
    """The server booked a different size than requested; the deal is open regardless."""

    def __init__(self, requested: Decimal, confirmation: DealConfirmation) -> None:
        super().__init__(
            f"Deal {confirmation.deal_reference}: booked size {confirmation.size} instead of "
            f"{requested}. The deal is open; see .confirmation.position_id.",
            requested,
            confirmation,
        )
        self._requested = requested
        self._confirmation = confirmation

    @property
    def requested(self) -> Decimal:
        """Size the caller asked for."""
        return self._requested

    @property
    def confirmation(self) -> DealConfirmation:
        """Confirmation of the deal as booked."""
        return self._confirmation


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
        deal_id = optional_str(item, "dealId")
        if deal_id is None:
            raise format_error("affectedDeals.dealId", "missing")
        deals.append(AffectedDeal(deal_id, optional_str(item, "status") or ""))
    return tuple(deals)
