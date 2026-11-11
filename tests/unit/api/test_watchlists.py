"""``cc.watchlists``."""

import json
from collections.abc import Iterator

import pytest
import responses

from capitalcom.api.client import CapitalCom
from capitalcom.domain.errors import ApiError, ValidationError
from capitalcom.domain.watchlist import Watchlist, WatchlistCreation
from tests.unit.api.test_facade import DEMO, TOKENS
from tests.unit.market_payloads import market_row, wire

LISTS = f"{DEMO}/api/v1/watchlists"


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.post(f"{DEMO}/api/v1/session", json={"currentAccountId": "A"}, headers=TOKENS)
        yield mock


def client() -> CapitalCom:
    return CapitalCom("wl-key-0001", "me@example.com", "wl-pw-0001")


def last_body(mock: responses.RequestsMock) -> object:
    body = mock.calls[-1].request.body
    assert body is not None
    return json.loads(body)


def test_list_reads_every_watchlist(api: responses.RequestsMock) -> None:
    api.get(
        LISTS,
        json={
            "watchlists": [
                {
                    "id": "123456",
                    "name": "Hello world",
                    "editable": True,
                    "deleteable": True,
                    "defaultSystemWatchlist": False,
                }
            ]
        },
    )
    assert client().watchlists.list() == (Watchlist("123456", "Hello world", True, True, False),)


def test_create_reports_epics_the_server_left_out(api: responses.RequestsMock) -> None:
    api.post(LISTS, json={"watchlistId": "123459", "status": "SUCCESS_NOT_ALL_INSTRUMENTS_ADDED"})
    created = client().watchlists.create("Lorem", ["SILVER", "NOSUCH"])
    assert created == WatchlistCreation("123459", all_epics_added=False)
    assert last_body(api) == {"name": "Lorem", "epics": ["SILVER", "NOSUCH"]}


def test_create_without_epics_sends_the_name_only(api: responses.RequestsMock) -> None:
    api.post(LISTS, json={"watchlistId": "123458", "status": "SUCCESS"})
    assert client().watchlists.create("x" * 20) == WatchlistCreation("123458", True)
    assert last_body(api) == {"name": "x" * 20}


def test_create_raises_on_an_unknown_status(api: responses.RequestsMock) -> None:
    api.post(LISTS, json={"watchlistId": "1", "status": "FAILED"})
    with pytest.raises(ApiError, match="FAILED"):
        client().watchlists.create("Lorem")


@pytest.mark.parametrize(
    ("name", "epics"), [("x" * 21, ()), ("", ()), (None, ()), ("ok", "SILVER"), ("ok", [""])]
)
def test_create_refuses_bad_input(api: responses.RequestsMock, name: object, epics: object) -> None:
    with pytest.raises(ValidationError):
        client().watchlists.create(name, epics)  # type: ignore[arg-type]
    assert len(api.calls) == 0


def test_get_lists_markets_with_their_pip_scale(api: responses.RequestsMock) -> None:
    rows = [market_row("SILVER", 2, "0.001"), market_row("NATURALGAS", 3, "0.0001")]
    api.get(f"{LISTS}/123", json=wire({"markets": rows}))
    markets = client().watchlists.get("123")
    assert [m.pip.position for m in markets] == [2, 3]


def test_add_market_sends_the_epic(api: responses.RequestsMock) -> None:
    api.put(f"{LISTS}/123", json={"status": "SUCCESS"})
    client().watchlists.add_market("123", "SILVER")
    assert last_body(api) == {"epic": "SILVER"}


def test_remove_market_encodes_both_segments(api: responses.RequestsMock) -> None:
    api.delete(f"{LISTS}/1%202/A%2FB", json={"status": "SUCCESS"})
    client().watchlists.remove_market("1 2", "A/B")
    assert api.calls[-1].request.url == f"{LISTS}/1%202/A%2FB"


@pytest.mark.parametrize(("wid", "epic"), [("123", ""), ("..", "session"), ("", "SILVER")])
def test_remove_market_refuses_path_breaking_segments(
    api: responses.RequestsMock, wid: str, epic: str
) -> None:
    with pytest.raises(ValidationError):
        client().watchlists.remove_market(wid, epic)
    assert len(api.calls) == 0


def test_delete_raises_unless_the_server_confirms(api: responses.RequestsMock) -> None:
    api.delete(f"{LISTS}/123", json={"status": "SUCCESS"})
    client().watchlists.delete("123")
    api.delete(f"{LISTS}/124", json={"status": "PENDING"})
    with pytest.raises(ApiError, match="PENDING"):
        client().watchlists.delete("124")


@pytest.mark.parametrize("epic", ["", None])
def test_add_market_refuses_a_blank_epic(api: responses.RequestsMock, epic: object) -> None:
    with pytest.raises(ValidationError, match="epic"):
        client().watchlists.add_market("123", epic)  # type: ignore[arg-type]
    assert len(api.calls) == 0
