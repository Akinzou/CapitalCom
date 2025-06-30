import requests
import time
import logging

# ANSI color codes for terminal coloring
RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def colored_log(level, text):
    color = {
        'INFO': GREEN,
        'ERROR': RED,
        'DEBUG': BLUE,
        'WARNING': RED
    }.get(level, '')
    logging.log(getattr(logging, level), f"{color}{text}{RESET}")

class CapitalClient:
    def __init__(self, api_key, login, password, demo=True):
        self.api_key = api_key
        self.login = login
        self.password = password
        self.base_url = 'https://demo-api-capital.backend-capital.com' if demo else 'https://api-capital.backend-capital.com'
        self.session = requests.Session()
        self.cst = None
        self.security_token = None
        self.token_expiry = 0
        self.login_session()  # Automatically authenticate upon creation

    def login_session(self):
        """Authenticate and store session tokens (CST and X-SECURITY-TOKEN)."""
        url = f'{self.base_url}/api/v1/session'
        headers = {
            'Content-Type': 'application/json',
            'X-CAP-API-KEY': self.api_key
        }
        payload = {
            'identifier': self.login,
            'password': self.password
        }

        response = self.session.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            self.cst = response.headers['CST']
            self.security_token = response.headers['X-SECURITY-TOKEN']
            self.token_expiry = time.time() + 600  # Capital.com sessions expire after 10 minutes of inactivity
            colored_log("INFO", "Session opened successfully.")
        else:
            colored_log("ERROR", f"Login failed: {response.status_code} {response.text}")
            raise Exception(f"Login failed: {response.status_code} {response.text}")

    def _headers(self):
        """Return the required headers for authenticated API requests."""
        return {
            'CST': self.cst,
            'X-SECURITY-TOKEN': self.security_token
        }

    def _request(self, method, path, **kwargs):
        """
        Make an authenticated API request.
        Automatically re-authenticates if the token has expired or if a 401 response is received.
        """
        if time.time() > self.token_expiry:
            colored_log("DEBUG", "Session expired. Renewing...")
            self.login_session()

        url = f"{self.base_url}{path}"
        headers = kwargs.pop('headers', {})
        headers.update(self._headers())

        response = self.session.request(method, url, headers=headers, **kwargs)

        if response.status_code == 401:
            colored_log("DEBUG", "Token invalid. Retrying request after re-authentication...")
            self.login_session()
            headers = self._headers()
            response = self.session.request(method, url, headers=headers, **kwargs)

        return response

    def get_session_info(self):
        """Return current session details, including accountId and clientId."""
        resp = self._request('GET', '/api/v1/session')
        if resp.status_code == 200:
            return resp.json()
        else:
            raise Exception(f"GET /session failed: {resp.status_code} {resp.text}")

    def search_instrument(self, term):
        """Search for an instrument using a name or symbol (via market navigation)."""
        resp = self._request('GET', '/api/v1/marketnavigation/search', params={'query': term})
        if resp.status_code == 200:
            return resp.json().get("markets", [])
        else:
            raise Exception(f"Instrument search failed: {resp.status_code} {resp.text}")

    def list_all_instruments(self):
        """
        Recursively list all instruments across all market navigation nodes.
        Useful for building custom instrument pickers or watchlists.
        """
        def recurse(node_id=""):
            instruments = []
            path = f"/api/v1/marketnavigation/{node_id}" if node_id else "/api/v1/marketnavigation"
            resp = self._request('GET', path)
            if resp.status_code != 200:
                colored_log("ERROR", f"Error while fetching {path}")
                return instruments

            data = resp.json()
            instruments += data.get('markets', [])
            for node in data.get('nodes', []):
                node_id = node.get('id')
                if node_id:
                    instruments += recurse(node_id)
            return instruments

        return recurse()

    def search_markets(self, term):
        """Search for markets directly (by name or epic) using the /markets endpoint."""
        resp = self._request('GET', '/api/v1/markets', params={'searchTerm': term})
        if resp.status_code == 200:
            return resp.json().get("markets", [])
        else:
            raise Exception(f"GET /markets failed: {resp.status_code} {resp.text}")

    def open_raw_position(self, epic, size, direction, stop_dist=None, profit_dist=None):
        """
        Open a raw market position and return the resolved dealId (not just dealReference).
        Uses polling because Capital.com does not return dealId directly.
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

        # Poll open positions until the new one appears
        timeout = 10
        start = time.time()
        while time.time() - start < timeout:
            positions = self.get_open_positions()
            filtered = [p for p in positions if p['market']['epic'] == epic]
            if filtered:
                latest = sorted(filtered, key=lambda p: p['position']['createdDate'], reverse=True)[0]
                colored_log("INFO", f"Position opened. Deal ID: {latest['position']['dealId']}")
                return latest['position']['dealId']
            time.sleep(0.5)

        raise Exception(f"Position not found for epic: {epic} within {timeout}s")

    def open_forex_position(self, epic, size, direction, stop_dist=None, profit_dist=None):
        """
        Open a position with lot size conversion and optional stop-loss / take-profit (in pips).
        """
        return self.open_raw_position(
            epic,
            self.lot_to_size(size, 100000),
            direction,
            self.pips_to_profit_distance(stop_dist, 5),
            self.pips_to_profit_distance(profit_dist, 5)
        )

    def get_open_positions(self):
        """Return all currently open positions on the account."""
        resp = self._request('GET', '/api/v1/positions')
        if resp.status_code == 200:
            return resp.json().get('positions', [])
        else:
            raise Exception(f"GET /positions failed: {resp.status_code} {resp.text}")

    def close_position_by_id(self, deal_id, size=None):
        """Close a full or partial position based on dealId."""
        payload = {"dealId": deal_id}
        if size:
            payload["size"] = size

        resp = self._request("DELETE", "/api/v1/positions", json=payload)
        if resp.status_code == 200:
            colored_log("INFO", f"Position closed successfully: {deal_id}")
            return "SUCCESS"
        else:
            raise Exception(f"Error closing position: {resp.status_code} {resp.text}")

    def lot_to_size(self, lot, lot_size):
        """Convert a lot amount (e.g., 0.01) into raw size units (e.g., 1000)."""
        return lot * lot_size

    def pips_to_profit_distance(self, pips, pip_position):
        """Convert pips into profitDistance format based on pip position (e.g., 5-digit pricing)."""
        return pips * 10 ** (-pip_position) if pips else None

    def get_balance(self, account_id=None, raw=False):
        """
        Return the current account balance and available funds.

        Parameters:
            raw (bool): If True, returns the full balance structure.
            account_id (str): Optional. If provided, selects balance for this account.
        """
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
        """
        List all available accounts with their ID, currency, and balance.
        """
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
        """
        Add funds to the demo account.

        Limits:
            • Max 10 requests/sec
            • Max 100 requests/account/day
            • Maximum balance after top-up: 100,000 units
        """
        payload = {"amount": amount}
        resp = self._request("POST", "/api/v1/accounts/topUp", json=payload)
        if resp.status_code == 200:
            colored_log("INFO", "Demo account topped up successfully.")
        else:
            raise Exception(f"Error topping up demo account: {resp.status_code} {resp.text}")

    def test_trade(self):
        """
        Open and close a small test trade to verify functionality.
        Uses fixed epic (EURUSD) and 0.001 lot.
        """
        epic = "EURUSD"
        lot = 0.001
        direction = "BUY"

        colored_log("INFO", "Opening test position on EUR/USD (0.001 lot)...")
        try:
            deal_id = self.open_forex_position(
                epic=epic,
                size=lot,
                direction=direction,
                stop_dist=100,
                profit_dist=200
            )
            colored_log("INFO", f"Position opened. Deal ID: {deal_id}")
        except Exception as e:
            colored_log("ERROR", f"Failed to open position: {e}")
            return

        colored_log("DEBUG", "Waiting 5 seconds before closing...")
        time.sleep(5)

        colored_log("DEBUG", "Closing position...")
        try:
            result = self.close_position_by_id(deal_id)
            colored_log("INFO", f"Position closed: {result}")
        except Exception as e:
            colored_log("ERROR", f"Failed to close position: {e}")
