"""``cc.prices``: historical price bars."""

from datetime import datetime

from capitalcom.api.composition import Core
from capitalcom.application.result import Err
from capitalcom.domain.enums import Resolution
from capitalcom.domain.errors import NotFoundError
from capitalcom.domain.parsing import as_mapping, require_list
from capitalcom.domain.prices import PriceBar, price_params
from capitalcom.domain.request_values import path_segment

# The server answers a window without bars with this 404. It is an empty answer, not a
# failure; an unknown epic has its own code (error.not-found.epic) and is still raised.
NO_BARS = "error.prices.not-found"


class PricesResource:
    """Historical prices."""

    def __init__(self, core: Core) -> None:
        self._core = core

    def history(
        self,
        epic: str,
        resolution: Resolution | None = None,
        *,
        limit: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[PriceBar, ...]:
        """Bars of ``epic``, oldest first; ``()`` when the window holds none.

        Without arguments the server returns the last 10 one-minute bars. ``limit`` is
        1..1000; ``start`` and ``end`` must be timezone-aware.
        """
        path = f"/api/v1/prices/{path_segment(epic, 'epic')}"
        params = price_params(resolution, limit, start, end)
        result = self._core.api.call("GET", path, params=params)
        if (
            isinstance(result, Err)
            and isinstance(result.error, NotFoundError)
            and result.error.error_code == NO_BARS
        ):
            return ()
        items = require_list(as_mapping(result.unwrap(), "prices"), "prices")
        return tuple(PriceBar.from_api(as_mapping(item, "prices[]")) for item in items)
