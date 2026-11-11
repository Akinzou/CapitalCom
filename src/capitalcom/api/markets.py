"""``cc.markets``: navigation, search and market details."""

from collections.abc import Iterable, Mapping

from capitalcom.api.composition import Core
from capitalcom.application.result import Err
from capitalcom.domain.errors import NotFoundError, ValidationError
from capitalcom.domain.market_details import MarketDetails, PipScale
from capitalcom.domain.markets import Market, MarketNode, NodeContents, markets_from, nodes_from
from capitalcom.domain.parsing import as_mapping, require_list
from capitalcom.domain.request_values import comma_list, path_segment

# Documented limits: GET /marketnavigation/{nodeId} takes limit 1..500, GET /markets at
# most 50 epics; the server answers more with a 400.
MAX_NODE_LIMIT = 500
MAX_EPICS = 50


class MarketsResource:
    """Markets and their details."""

    def __init__(self, core: Core) -> None:
        self._core = core

    def navigation(self) -> tuple[MarketNode, ...]:
        """Top-level nodes of the market tree (``GET /api/v1/marketnavigation``)."""
        body = self._core.api.call("GET", "/api/v1/marketnavigation").unwrap()
        return nodes_from(as_mapping(body, "marketnavigation"))

    def browse(self, node_id: str, *, limit: int | None = None) -> NodeContents:
        """Children of ``node_id``: sub-nodes, or the markets of a leaf node."""
        path = f"/api/v1/marketnavigation/{path_segment(node_id, 'node_id')}"
        params: dict[str, str] = {}
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise ValidationError(f"limit must be an int, got {limit!r}")
            if not 1 <= limit <= MAX_NODE_LIMIT:
                raise ValidationError(f"limit must be within 1..{MAX_NODE_LIMIT}, got {limit}")
            params["limit"] = str(limit)
        return NodeContents.from_api(self._core.api.call("GET", path, params=params).unwrap())

    def search(self, term: str) -> tuple[Market, ...]:
        """Markets whose name or epic matches ``term``."""
        if not isinstance(term, str) or not term.strip():
            raise ValidationError("search term must be a non-blank string")
        return self._rows({"searchTerm": term})

    def all(self) -> tuple[Market, ...]:
        """Every market the account can see; about 4000 rows in one response."""
        return self._rows(None)

    def get(self, epic: str) -> MarketDetails:
        """Details of one market, with its pip scale.

        Two reads: the details carry no pip data, so the latest price bar
        (``GET /prices/{epic}?max=1``) supplies ``pipPosition`` and ``tickSize``. When that
        market has no price data the pip scale stays ``None``; any other error is raised.
        """
        segment = path_segment(epic, "epic")
        body = self._core.api.call("GET", f"/api/v1/markets/{segment}").unwrap()
        prices = self._core.api.call("GET", f"/api/v1/prices/{segment}", params={"max": "1"})
        pip: PipScale | None = None
        if isinstance(prices, Err):
            if not isinstance(prices.error, NotFoundError):
                prices.unwrap()
        else:
            pip = PipScale.from_api(as_mapping(prices.value, "prices"))
        return MarketDetails.from_api(body, pip)

    def get_many(self, epics: Iterable[str]) -> Mapping[str, MarketDetails]:
        """Details of up to 50 markets in one request, keyed by epic in request order.

        The pip scale is ``None`` on every item: one request cannot fetch it. The server
        silently drops unknown or wrong-case epics; they raise ``NotFoundError`` here.
        """
        joined = comma_list(epics, "epics", max_items=MAX_EPICS)
        body = self._core.api.call("GET", "/api/v1/markets", params={"epics": joined}).unwrap()
        items = require_list(as_mapping(body, "markets"), "marketDetails")
        found = {
            parsed.instrument.epic: parsed
            for parsed in (MarketDetails.from_api(item) for item in items)
        }
        wanted = joined.split(",")
        missing = [epic for epic in wanted if epic not in found]
        if missing:
            raise NotFoundError(200, None, f"no market for epics: {missing}")
        return {epic: found[epic] for epic in wanted}

    def _rows(self, params: Mapping[str, str] | None) -> tuple[Market, ...]:
        body = self._core.api.call("GET", "/api/v1/markets", params=params).unwrap()
        return markets_from(as_mapping(body, "markets"), "markets")
