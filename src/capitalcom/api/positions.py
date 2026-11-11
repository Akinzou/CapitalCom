"""``cc.positions``: open, read, amend and close positions."""

from decimal import Decimal

from capitalcom.api.composition import Core
from capitalcom.api.dealing import submit
from capitalcom.domain.confirmation import DealConfirmation
from capitalcom.domain.enums import Direction
from capitalcom.domain.market_details import MarketDetails
from capitalcom.domain.order_request import OrderRequest
from capitalcom.domain.parsing import as_mapping
from capitalcom.domain.positions import Position, positions_from
from capitalcom.domain.protection import StopLoss, TakeProfit, protection_body
from capitalcom.domain.request_values import path_segment

_ROOT = "/api/v1/positions"


class PositionsResource:
    """Open positions of the current account."""

    def __init__(self, core: Core) -> None:
        self._core = core

    def list(self) -> tuple[Position, ...]:
        """Every open position."""
        body = self._core.api.call("GET", _ROOT).unwrap()
        return positions_from(as_mapping(body, "positions"))

    def get(self, position_id: str) -> Position:
        """One open position; a closed one raises ``NotFoundError``."""
        body = self._core.api.call("GET", self._path(position_id)).unwrap()
        return Position.from_api(as_mapping(body, "position"))

    def open(
        self,
        epic: str,
        direction: Direction | str,
        size: Decimal | int,
        *,
        stop: StopLoss | None = None,
        profit: TakeProfit | None = None,
        instrument: MarketDetails | None = None,
    ) -> DealConfirmation:
        """Open a position at market and return its confirmation.

        The new position's id is ``confirmation.position_id``. With ``instrument`` (from
        ``cc.markets.get(epic)``) the size is checked against the dealing rules first.
        ``SizeAdjustedError`` means the server booked another size; the deal was booked.
        """
        request = OrderRequest(epic, direction, size, stop, profit)
        if instrument is not None:
            instrument.validate(request)
        confirmation = submit(self._core, "POST", _ROOT, request.to_body())
        return confirmation.require_size(request.size)

    def amend(
        self, position_id: str, *, stop: StopLoss | None, profit: TakeProfit | None
    ) -> DealConfirmation:
        """Set the position's stop and take-profit; replaces all protection.

        The server drops whatever the request leaves out, so both sides are required: pass
        the current stop again to keep it, and ``None`` to remove it.
        """
        path = self._path(position_id)
        return submit(self._core, "PUT", path, protection_body(stop, profit))

    def close(self, position_id: str) -> DealConfirmation:
        """Close the whole position."""
        return submit(self._core, "DELETE", self._path(position_id))

    @staticmethod
    def _path(position_id: str) -> str:
        return f"{_ROOT}/{path_segment(position_id, 'position_id')}"
