"""``cc.history``: account activity and transactions."""

from datetime import datetime, timedelta

from capitalcom.api.composition import Core
from capitalcom.domain.history import Activity, Transaction, history_params
from capitalcom.domain.parsing import as_mapping, require_list

# GET /history/activity documents a one-day maximum for both a range and lastPeriod;
# GET /history/transactions documents none, so none is enforced there.
ACTIVITY_MAX_SPAN = timedelta(days=1)


class HistoryResource:
    """What happened on the account."""

    def __init__(self, core: Core) -> None:
        self._core = core

    def activity(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        last_period: timedelta | None = None,
        detailed: bool = False,
        deal_id: str | None = None,
        fiql: str | None = None,
    ) -> tuple[Activity, ...]:
        """Account events in a window of at most one day.

        ``start`` and ``end`` must be timezone-aware. ``fiql`` is sent as the ``filter``
        parameter, e.g. ``"epic==SILVER;status==ACCEPTED"``.
        """
        params = history_params(start, end, last_period, max_span=ACTIVITY_MAX_SPAN)
        if detailed:
            params["detailed"] = "true"
        if deal_id is not None:
            params["dealId"] = deal_id
        if fiql is not None:
            params["filter"] = fiql
        body = self._core.api.call("GET", "/api/v1/history/activity", params=params).unwrap()
        items = require_list(as_mapping(body, "activity"), "activities")
        return tuple(Activity.from_api(as_mapping(item, "activities[]")) for item in items)

    def transactions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        last_period: timedelta | None = None,
        transaction_type: str | None = None,
    ) -> tuple[Transaction, ...]:
        """Money movements; ``transaction_type`` (e.g. ``"TRADE"``) is sent as ``type``."""
        params = history_params(start, end, last_period, max_span=None)
        if transaction_type is not None:
            params["type"] = transaction_type
        path = "/api/v1/history/transactions"
        body = self._core.api.call("GET", path, params=params).unwrap()
        items = require_list(as_mapping(body, "transactions"), "transactions")
        return tuple(Transaction.from_api(as_mapping(item, "transactions[]")) for item in items)
