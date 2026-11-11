"""``cc.watchlists``: the client's lists of markets."""

from collections.abc import Iterable, Mapping
from typing import Any

from capitalcom.api.composition import Core
from capitalcom.domain.errors import ApiError
from capitalcom.domain.markets import Market, markets_from
from capitalcom.domain.parsing import as_mapping, require_list
from capitalcom.domain.request_values import comma_list, path_segment
from capitalcom.domain.watchlist import Watchlist, WatchlistCreation, check_name

_ROOT = "/api/v1/watchlists"


class WatchlistsResource:
    """Watchlists."""

    def __init__(self, core: Core) -> None:
        self._core = core

    def list(self) -> tuple[Watchlist, ...]:
        """Every watchlist of the client."""
        body = as_mapping(self._core.api.call("GET", _ROOT).unwrap(), "watchlists")
        items = require_list(body, "watchlists")
        return tuple(Watchlist.from_api(as_mapping(item, "watchlists[]")) for item in items)

    def create(self, name: str, epics: Iterable[str] = ()) -> WatchlistCreation:
        """Create a watchlist named ``name`` (1..20 characters), optionally with markets.

        Unknown epics do not fail the call: the list is created without them and
        ``all_epics_added`` is False.
        """
        body: dict[str, Any] = {"name": check_name(name)}
        given = epics if isinstance(epics, str) else list(epics)
        # A string is passed on so comma_list refuses it; an empty list sends no key.
        if isinstance(given, str) or given:
            body["epics"] = comma_list(given, "epics", max_items=None).split(",")
        answer = self._core.api.call("POST", _ROOT, json=body).unwrap()
        return WatchlistCreation.from_api(as_mapping(answer, "watchlists"))

    def get(self, watchlist_id: str) -> tuple[Market, ...]:
        """Markets on the watchlist."""
        body = self._core.api.call("GET", self._path(watchlist_id)).unwrap()
        return markets_from(as_mapping(body, "watchlist"), "markets")

    def add_market(self, watchlist_id: str, epic: str) -> None:
        """Add ``epic`` to the watchlist; adding one already on it succeeds."""
        path = self._path(watchlist_id)
        # The epic travels in the body, but it is checked by the same rule as a path
        # segment so a blank or non-string epic fails before the request.
        path_segment(epic, "epic")
        self._confirm("PUT", path, {"epic": epic})

    def remove_market(self, watchlist_id: str, epic: str) -> None:
        """Remove ``epic`` from the watchlist."""
        self._confirm("DELETE", f"{self._path(watchlist_id)}/{path_segment(epic, 'epic')}")

    def delete(self, watchlist_id: str) -> None:
        """Delete the watchlist."""
        self._confirm("DELETE", self._path(watchlist_id))

    @staticmethod
    def _path(watchlist_id: str) -> str:
        return f"{_ROOT}/{path_segment(watchlist_id, 'watchlist_id')}"

    def _confirm(self, method: str, path: str, json: Mapping[str, Any] | None = None) -> None:
        answer = self._core.api.call(method, path, json=json).unwrap()
        if not isinstance(answer, Mapping) or answer.get("status") != "SUCCESS":
            raise ApiError(200, None, f"watchlist not changed: {answer!r}")
