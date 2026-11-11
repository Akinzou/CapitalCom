"""``cc.sentiment``: how clients are positioned on a market."""

from collections.abc import Iterable, Mapping

from capitalcom.api.composition import Core
from capitalcom.domain.parsing import as_mapping, require_list
from capitalcom.domain.request_values import comma_list, path_segment
from capitalcom.domain.sentiment import Sentiment


class SentimentResource:
    """Client sentiment."""

    def __init__(self, core: Core) -> None:
        self._core = core

    def get(self, market_id: str) -> Sentiment:
        """Sentiment of one market; ``market_id`` is the epic."""
        path = f"/api/v1/clientsentiment/{path_segment(market_id, 'market_id')}"
        body = self._core.api.call("GET", path).unwrap()
        return Sentiment.from_api(as_mapping(body, "clientsentiment"))

    def get_many(self, market_ids: Iterable[str]) -> Mapping[str, Sentiment]:
        """Sentiment of several markets in one request, keyed by market id.

        One unknown id fails the whole call with ``NotFoundError``; the server does not
        answer for the others.
        """
        joined = comma_list(market_ids, "market_ids", max_items=None)
        body = self._core.api.call(
            "GET", "/api/v1/clientsentiment", params={"marketIds": joined}
        ).unwrap()
        items = require_list(as_mapping(body, "clientsentiment"), "clientSentiments")
        parsed = (Sentiment.from_api(as_mapping(item, "clientSentiments[]")) for item in items)
        return {sentiment.market_id: sentiment for sentiment in parsed}
