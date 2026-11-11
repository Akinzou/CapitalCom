"""1.x API: ``CapitalClient``, kept working on top of the 2.x core until 3.0.

New code should use ``capitalcom.CapitalCom``. Every name here emits one ``DeprecationWarning``
per process; the migration guide maps each call to its 2.x equivalent.
"""

import logging
import time
from typing import Any

import requests

from capitalcom.api.dealing import submit
from capitalcom.api.positions import PositionsResource
from capitalcom.application.logs import get_logger
from capitalcom.domain.errors import ValidationError
from capitalcom.legacy.attributes import LegacyAttributes
from capitalcom.legacy.deprecation import warn_once
from capitalcom.legacy.raw_request import send_raw
from capitalcom.legacy.trading import (
    affected_deal_id,
    open_body,
    resolve_deal_id,
    warn_if_resized,
)
from capitalcom.legacy.wiring import legacy_core

# 1.0.4 code doing "from capitalcom import *" got these six names (and, by accident, the
# requests, time, logging and random modules, which are no longer re-exported).
__all__ = ["BLUE", "GREEN", "RED", "RESET", "CapitalClient", "colored_log"]

# Kept importable with their 1.0.4 values; the library no longer writes them into log lines,
# where they ended up as escape garbage in files and log collectors.
RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"

_log = get_logger(__name__)

_JPY_FLAW = (
    "It scales distances by 0.00001, the fractional pip of five-decimal pairs; JPY pairs quote "
    "to three decimals, so their distances come out 100 times too small. Pass distances in "
    "price units to CapitalCom.positions.open instead"
)


def colored_log(level: str, text: str) -> None:
    """Log ``text`` at ``level`` (a level name such as ``"INFO"``) under ``capitalcom.client``.

    Unlike 1.0.4 it neither colours the text nor configures the root logger: the application
    decides where library logs go.
    """
    _log.log(logging.getLevelNamesMapping()[level], text)


class CapitalClient(LegacyAttributes):
    """Deprecated 1.x client; use ``capitalcom.CapitalCom``.

    It logs in when constructed. Its 1.0.4 attributes live in ``LegacyAttributes``.
    """

    def __init__(self, api_key: str, login: str, password: str, demo: bool = True) -> None:
        warn_once("CapitalClient")
        self._api_key = api_key
        self._login = login
        self._password = password
        self._session = requests.Session()
        self._core = legacy_core(api_key, login, password, demo, self._session)
        self._base_url = self._core.environment.rest_url
        self._log_in()

    def __repr__(self) -> str:
        # The login is an e-mail address and the other two are secrets.
        return f"CapitalClient(base_url={self._base_url!r})"

    def login_session(self) -> None:
        """Log in again, replacing the current session tokens."""
        warn_once("CapitalClient.login_session")
        self._log_in()

    def _log_in(self) -> None:
        self._core.session.adopt_tokens(None, None)
        try:
            self._core.session.tokens().unwrap()
        except Exception as error:
            colored_log("ERROR", f"Login failed: {error}")
            raise
        colored_log("INFO", "Session opened successfully.")

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Authenticated request returning the raw response, whatever its status."""
        return send_raw(self._core, self._session, self._base_url, method, path, kwargs)

    def lot_to_size(self, lot: float, lot_size: float) -> float:
        """``lot * lot_size``."""
        warn_once("CapitalClient.lot_to_size")
        return lot * lot_size

    def pips_to_profit_distance(self, pips: float | None, pip_position: int) -> float | None:
        """``pips * 10 ** -pip_position``; ``None`` for a falsy ``pips``."""
        warn_once("CapitalClient.pips_to_profit_distance")
        return _pips_to_distance(pips, pip_position)

    def get_deal_by_ref(self, deal_reference: str, retries: int = 10, delay: float = 0.1) -> str:
        """The dealId of the first deal ``deal_reference`` affected, once it is confirmed."""
        warn_once("CapitalClient.get_deal_by_ref")
        return resolve_deal_id(self._core, deal_reference, retries, delay)

    def open_raw_position(
        self,
        epic: str,
        size: float,
        direction: str,
        stop_dist: float | None = None,
        profit_dist: float | None = None,
    ) -> str:
        """Open a market position and return its dealId once the deal is confirmed."""
        warn_once("CapitalClient.open_raw_position")
        return self._open(epic, size, direction, stop_dist, profit_dist)

    def open_forex_position(
        self,
        epic: str,
        size: float,
        direction: str,
        stop_dist: float | None = None,
        profit_dist: float | None = None,
    ) -> str:
        """Open ``size`` lots of 100000 units, with distances in pips of 0.00001."""
        warn_once("CapitalClient.open_forex_position", _JPY_FLAW)
        stop, profit = _pips_to_distance(stop_dist, 5), _pips_to_distance(profit_dist, 5)
        return self._open(epic, size * 100000, direction, stop, profit)

    def close_position_by_id(self, deal_id: str, size: float | None = None) -> str:
        """Close the whole position and return ``"SUCCESS"`` once it is confirmed."""
        warn_once("CapitalClient.close_position_by_id")
        return self._close(deal_id, size)

    def close_position_by_ref(self, deal_reference: str, size: float | None = None) -> str:
        """Resolve the dealId of ``deal_reference``, then close that whole position."""
        warn_once("CapitalClient.close_position_by_ref")
        _refuse_partial(size)
        return self._close(resolve_deal_id(self._core, deal_reference, 10, 0.1), size)

    def test_trade(self) -> None:
        """Open 0.001 lot of EURUSD, wait 5 s and close it; errors are logged, not raised."""
        warn_once("CapitalClient.test_trade")
        colored_log("INFO", "Opening test position on EUR/USD (0.001 lot)...")
        try:
            deal_id = self._open("EURUSD", 0.001 * 100000, "BUY", 100 * 10**-5, 200 * 10**-5)
        except Exception as error:  # noqa: BLE001 - 1.0.4 swallowed every failure here
            colored_log("ERROR", f"Failed to open position: {error}")
            return
        colored_log("DEBUG", "Waiting 5 seconds before closing...")
        self._core.clock.sleep(5)
        colored_log("DEBUG", "Closing position...")
        try:
            # By id: 1.0.4 passed this dealId to close_position_by_ref, which asked /confirms
            # with it; if that never resolved, the test position stayed open.
            colored_log("INFO", f"Position closed: {self._close(deal_id, None)}")
        except Exception as error:  # noqa: BLE001 - 1.0.4 swallowed every failure here
            colored_log("ERROR", f"Failed to close position: {error}")

    def _open(
        self,
        epic: str,
        size: float,
        direction: str,
        stop_dist: float | None,
        profit_dist: float | None,
    ) -> str:
        body = open_body(epic, size, direction, stop_dist, profit_dist)
        confirmation = submit(self._core, "POST", "/api/v1/positions", body)
        warn_if_resized(size, confirmation)
        deal_id = affected_deal_id(confirmation)
        colored_log("INFO", f"Position opened. Deal ID: {deal_id}")
        return deal_id

    def _close(self, deal_id: str, size: float | None) -> str:
        _refuse_partial(size)
        PositionsResource(self._core).close(deal_id)
        colored_log("INFO", f"Position closed successfully: {deal_id}")
        return "SUCCESS"

    def get_open_positions(self):
        resp = self._request('GET', '/api/v1/positions')
        if resp.status_code == 200:
            return resp.json().get('positions', [])
        else:
            raise Exception(f"GET /positions failed: {resp.status_code} {resp.text}")

    def get_balance(self, account_id=None, raw=False):
        resp = self._request("GET", "/api/v1/accounts")
        if resp.status_code != 200:
            raise Exception(f"GET /accounts failed: {resp.status_code} {resp.text}")

        accounts = resp.json().get("accounts", [])
        if not accounts:
            raise Exception("No accounts found.")

        account = next((acc for acc in accounts if acc.get("accountId") == account_id), accounts[0])
        balance = account.get("balance")

        if raw:
            return {
                "balance": balance,
                "available": account.get("available"),
                "currency": account.get("currency")
            }
        else:
            return balance['balance']

    def list_accounts(self):
        resp = self._request("GET", "/api/v1/accounts")
        if resp.status_code != 200:
            raise Exception(f"GET /accounts failed: {resp.status_code} {resp.text}")

        accounts = resp.json().get("accounts", [])
        if not accounts:
            colored_log("ERROR", "No accounts found.")
            return []

        for acc in accounts:
            acc_id = acc.get("accountId", "N/A")
            currency = acc.get("currency", "N/A")
            balance = acc.get("balance", {}).get("balance", "N/A")
            colored_log("INFO", f"Account ID: {acc_id}, Currency: {currency}, Balance: {balance}")

        return accounts

    def top_up_demo(self, amount):
        payload = {"amount": amount}
        resp = self._request("POST", "/api/v1/accounts/topUp", json=payload)
        if resp.status_code == 200:
            colored_log("INFO", "Demo account topped up successfully.")
        else:
            raise Exception(f"Error topping up demo account: {resp.status_code} {resp.text}")


def _pips_to_distance(pips: float | None, pip_position: int) -> float | None:
    return pips * 10 ** (-pip_position) if pips else None


def _refuse_partial(size: float | None) -> None:
    # 1.0.4 tested size for truthiness, so size=0 has always meant "close everything".
    if size:
        raise ValidationError(
            "a legacy close cannot close part of a position: Capital.com closes the whole "
            "position whatever size is sent; call it without size to close the whole position"
        )
