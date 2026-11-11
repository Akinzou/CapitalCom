"""``cc.markets``."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.errors import ApiError, NotFoundError, ValidationError
from tests.unit.api.test_facade import DEMO, TOKENS
from tests.unit.market_payloads import details, market_row, wire

MARKETS = f"{DEMO}/api/v1/markets"


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(f"{DEMO}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        yield mock


def client() -> CapitalCom:
    return CapitalCom("mkt-key-0001", "me@example.com", "mkt-pw-0001")


def sent(mock: responses.RequestsMock) -> list[str]:
    """URLs of the requests after the login."""
    return [c.request.url or "" for c in mock.calls if not c.request.url.endswith("/session")]  # type: ignore[union-attr]


def test_navigation_lists_top_nodes(api: responses.RequestsMock) -> None:
    api.get(f"{DEMO}/api/v1/marketnavigation", json={"nodes": [{"id": "n1", "name": "Most"}]})
    (node,) = client().markets.navigation()
    assert (node.node_id, node.name) == ("n1", "Most")


def test_browse_encodes_the_node_and_sends_the_limit(api: responses.RequestsMock) -> None:
    api.get(
        f"{DEMO}/api/v1/marketnavigation/a%2Fb", json=wire({"nodes": [], "markets": [market_row()]})
    )
    contents = client().markets.browse("a/b", limit=2)
    assert [m.epic for m in contents.markets] == ["USDJPY"]
    assert sent(api) == [f"{DEMO}/api/v1/marketnavigation/a%2Fb?limit=2"]


@pytest.mark.parametrize("limit", [0, 501, True, "5"])
def test_browse_refuses_a_limit_outside_1_to_500(
    api: responses.RequestsMock, limit: object
) -> None:
    with pytest.raises(ValidationError, match="limit"):
        client().markets.browse("n1", limit=limit)  # type: ignore[arg-type]
    assert len(api.calls) == 0


def test_search_sends_the_term(api: responses.RequestsMock) -> None:
    api.get(MARKETS, json=wire({"markets": [market_row("EURUSD", 4, "0.00001")]}))
    (market,) = client().markets.search("EUR USD")
    assert market.pip.size == Decimal("0.0001")
    assert sent(api) == [f"{MARKETS}?searchTerm=EUR+USD"]


@pytest.mark.parametrize("term", ["", " ", None])
def test_search_refuses_a_blank_term(api: responses.RequestsMock, term: object) -> None:
    with pytest.raises(ValidationError, match="term"):
        client().markets.search(term)  # type: ignore[arg-type]
    assert len(api.calls) == 0


def test_all_sends_no_parameters(api: responses.RequestsMock) -> None:
    api.get(MARKETS, json=wire({"markets": [market_row(), market_row("EURUSD", 4)]}))
    assert [m.epic for m in client().markets.all()] == ["USDJPY", "EURUSD"]
    assert sent(api) == [MARKETS]


def test_get_reads_the_pip_scale_from_one_price_bar(api: responses.RequestsMock) -> None:
    api.get(f"{MARKETS}/USDJPY", json=wire(details("USDJPY")))
    api.get(
        f"{DEMO}/api/v1/prices/USDJPY",
        json={"prices": [], "instrumentType": "CURRENCIES", "pipPosition": 2, "tickSize": 0.001},
    )
    instrument = client().markets.get("USDJPY").instrument
    assert instrument.pip_size == Decimal("0.01")
    assert sent(api) == [f"{MARKETS}/USDJPY", f"{DEMO}/api/v1/prices/USDJPY?max=1"]


def test_get_without_price_data_leaves_the_pip_unknown(api: responses.RequestsMock) -> None:
    api.get(f"{MARKETS}/USDJPY", json=wire(details("USDJPY")))
    api.get(
        f"{DEMO}/api/v1/prices/USDJPY", status=404, json={"errorCode": "error.prices.not-found"}
    )
    assert client().markets.get("USDJPY").instrument.pip is None


def test_get_raises_other_price_errors(api: responses.RequestsMock) -> None:
    api.get(f"{MARKETS}/USDJPY", json=wire(details("USDJPY")))
    api.get(f"{DEMO}/api/v1/prices/USDJPY", status=400, json={"errorCode": "error.invalid.max"})
    with pytest.raises(ApiError) as caught:
        client().markets.get("USDJPY")
    assert caught.value.error_code == "error.invalid.max"


def test_get_encodes_the_epic(api: responses.RequestsMock) -> None:
    api.get(f"{MARKETS}/A%2FB", status=404, json={"errorCode": "error.not-found.epic"})
    with pytest.raises(NotFoundError):
        client().markets.get("A/B")
    assert sent(api) == [f"{MARKETS}/A%2FB"]


def test_get_many_keys_details_in_request_order(api: responses.RequestsMock) -> None:
    api.get(MARKETS, json=wire({"marketDetails": [details("USDJPY"), details("EURUSD")]}))
    found = client().markets.get_many(["USDJPY", "EURUSD", "USDJPY"])
    assert list(found) == ["USDJPY", "EURUSD"]
    assert found["EURUSD"].instrument.pip is None
    assert sent(api) == [f"{MARKETS}?epics=USDJPY%2CEURUSD"]


def test_get_many_names_epics_the_server_dropped(api: responses.RequestsMock) -> None:
    api.get(MARKETS, json=wire({"marketDetails": [details("BTCUSD")]}))
    with pytest.raises(NotFoundError, match="eurusd"):
        client().markets.get_many(["BTCUSD", "eurusd"])


@pytest.mark.parametrize("epics", ["EURUSD", [], [f"E{i}" for i in range(51)]])
def test_get_many_refuses_bad_epic_lists(api: responses.RequestsMock, epics: object) -> None:
    with pytest.raises(ValidationError, match="epics"):
        client().markets.get_many(epics)  # type: ignore[arg-type]
    assert len(api.calls) == 0


def test_get_raises_when_prices_do_not_know_the_epic(api: responses.RequestsMock) -> None:
    api.get(f"{MARKETS}/USDJPY", json=wire(details("USDJPY")))
    api.get(f"{DEMO}/api/v1/prices/USDJPY", status=404, json={"errorCode": "error.not-found.epic"})
    with pytest.raises(NotFoundError) as caught:
        client().markets.get("USDJPY")
    assert caught.value.error_code == "error.not-found.epic"


def test_browse_without_a_limit_sends_none(api: responses.RequestsMock) -> None:
    api.get(f"{DEMO}/api/v1/marketnavigation/n1", json={"nodes": []})
    assert client().markets.browse("n1").nodes == ()
    assert sent(api) == [f"{DEMO}/api/v1/marketnavigation/n1"]
