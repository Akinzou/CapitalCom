"""1.x API: ``CapitalClient``, kept working on top of the 2.x core until 3.0.

New code should use ``capitalcom.CapitalCom``. Every name here emits one ``DeprecationWarning``
per process; the migration guide maps each call to its 2.x equivalent.
"""

import logging
import time
from typing import Any

import requests

from capitalcom.application.logs import get_logger
from capitalcom.legacy.attributes import LegacyAttributes
from capitalcom.legacy.deprecation import warn_once
from capitalcom.legacy.raw_request import send_raw
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
        return pips * 10 ** (-pip_position) if pips else None

    def get_deal_by_ref(self, deal_reference, retries=10, delay=0.1):
        """
        Resolve dealId from dealReference, retrying on 404, invalid references, or incomplete confirms.
        """
        for attempt in range(retries):
            resp = self._request("GET", f"/api/v1/confirms/{deal_reference}")
            if resp.status_code == 200:
                data = resp.json()
                deals = data.get("affectedDeals", [])
                if deals and deals[0].get("dealId"):
                    return deals[0]["dealId"]
                else:
                    colored_log("DEBUG",
                                f"[Confirm Retry {attempt + 1}/{retries}] dealId missing in response. Waiting...")
                    time.sleep(delay)
                    continue

            elif resp.status_code == 404:
                colored_log("DEBUG", f"[Confirm Retry {attempt + 1}/{retries}] 404 Not ready yet. Waiting...")
                time.sleep(delay)
                continue

            elif resp.status_code == 400:
                err_json = resp.json()
                if err_json.get("errorCode") == "error.invalid.dealReference":
                    colored_log("DEBUG", f"[Confirm Retry {attempt + 1}/{retries}] Invalid dealReference. Waiting...")
                    time.sleep(delay)
                    continue
                else:
                    raise Exception(f"Confirm failed: {resp.status_code} {resp.text}")

            else:
                raise Exception(f"Confirm failed: {resp.status_code} {resp.text}")

        raise Exception(f"dealReference {deal_reference} not resolved after {retries} retries.")

    def open_raw_position(self, epic, size, direction, stop_dist=None, profit_dist=None):
        """
        Open a raw market position and return the dealId.
        Automatically confirms dealReference to retrieve dealId.
        """
        payload = {
            "epic": epic,
            "expiry": "-",
            "direction": direction,
            "size": size,
            "orderType": "MARKET",
            "guaranteedStop": False,
            "forceOpen": True,
        }
        if stop_dist:
            payload["stopDistance"] = stop_dist
        if profit_dist:
            payload["profitDistance"] = profit_dist

        resp = self._request("POST", "/api/v1/positions", json=payload)
        if resp.status_code != 200:
            raise Exception(f"Error opening position: {resp.status_code} {resp.text}")

        deal_ref = resp.json().get("dealReference")
        if not deal_ref:
            raise Exception("Missing dealReference in response")

        # Retry confirm to get dealId
        deal_id = self.get_deal_by_ref(deal_ref, retries=5, delay=0.1)
        colored_log("INFO", f"Position opened. Deal ID: {deal_id}")
        return deal_id

    def open_forex_position(self, epic, size, direction, stop_dist=None, profit_dist=None):
        return self.open_raw_position(
            epic,
            self.lot_to_size(size, 100000),
            direction,
            self.pips_to_profit_distance(stop_dist, 5),
            self.pips_to_profit_distance(profit_dist, 5)
        )

    def get_open_positions(self):
        resp = self._request('GET', '/api/v1/positions')
        if resp.status_code == 200:
            return resp.json().get('positions', [])
        else:
            raise Exception(f"GET /positions failed: {resp.status_code} {resp.text}")

    def close_position_by_id(self, deal_id, size=None):
        payload = {"dealId": deal_id}
        if size:
            payload["size"] = size

        resp = self._request("DELETE", "/api/v1/positions", json=payload)
        if resp.status_code == 200:
            colored_log("INFO", f"Position closed successfully: {deal_id}")
            return "SUCCESS"
        else:
            raise Exception(f"Error closing position: {resp.status_code} {resp.text}")

    def close_position_by_ref(self, deal_reference, size=None):
        """
        Resolve dealId from dealReference and close the position.
        """
        deal_id = self.get_deal_by_ref(deal_reference)
        return self.close_position_by_id(deal_id, size=size)


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

    def test_trade(self):
        epic = "EURUSD"
        lot = 0.001
        direction = "BUY"

        colored_log("INFO", "Opening test position on EUR/USD (0.001 lot)...")
        try:
            deal_ref = self.open_forex_position(
                epic=epic,
                size=lot,
                direction=direction,
                stop_dist=100,
                profit_dist=200
            )
            colored_log("INFO", f"Position opened. Deal Reference: {deal_ref}")
        except Exception as e:
            colored_log("ERROR", f"Failed to open position: {e}")
            return

        colored_log("DEBUG", "Waiting 5 seconds before closing...")
        time.sleep(5)

        colored_log("DEBUG", "Closing position...")
        try:
            result = self.close_position_by_ref(deal_ref)
            colored_log("INFO", f"Position closed: {result}")
        except Exception as e:
            colored_log("ERROR", f"Failed to close position: {e}")

