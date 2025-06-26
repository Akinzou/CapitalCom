import requests
import time

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
        """Authenticate and store session tokens (CST + X-SECURITY-TOKEN)."""
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
            self._print_green("Session opened successfully.")
        else:
            self._print_red(f"Login failed: {response.status_code} {response.text}")
            raise Exception(f"Login failed: {response.status_code} {response.text}")

    def _headers(self):
        """Return required headers for authenticated API requests."""
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
            self._print_blue("Session expired. Renewing...")
            self.login_session()

        url = f"{self.base_url}{path}"
        headers = kwargs.pop('headers', {})
        headers.update(self._headers())

        response = self.session.request(method, url, headers=headers, **kwargs)

        if response.status_code == 401:
            self._print_blue("Token invalid. Retrying request after re-authentication...")
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
                self._print_red(f"Error while fetching {path}")
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
        """Search markets directly (by name or epic) using the /markets endpoint."""
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

        # Poll open positions until we see the new one appear
        timeout = 10
        start = time.time()
        while time.time() - start < timeout:
            positions = self.get_open_positions()
            filtered = [p for p in positions if p['market']['epic'] == epic]
            if filtered:
                latest = sorted(filtered, key=lambda p: p['position']['createdDate'], reverse=True)[0]
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

    def pips_to_profit_distance(self, pips, pip_position):
        """Convert pips into profitDistance format based on pip position (e.g. 5 digits)."""
        return pips * 10 ** (-pip_position) if pips else None

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
            return "SUCCESS"
        else:
            raise Exception(f"Error closing position: {resp.status_code} {resp.text}")

    def lot_to_size(self, lot, lot_size):
        """Convert a lot amount (e.g. 0.01) into raw size units (e.g. 1000)."""
        return lot * lot_size

    def _print_green(self, text):
        print(f"\033[92m{text}\033[0m")  # bright green

    def _print_red(self, text):
        print(f"\033[91m{text}\033[0m")  # bright red

    def _print_blue(self, text):
        print(f"\033[94m{text}\033[0m")  # bright blue

    def test_trade(self):
        """
        Open and close a small test trade to verify functionality.
        Uses fixed epic (EURUSD) and 0.001 lot.
        """
        epic = "EURUSD"
        lot = 0.001
        direction = "BUY"

        self._print_blue("Opening test position on EUR/USD (0.001 lot)...")
        try:
            deal_id = self.open_forex_position(
                epic=epic,
                size=lot,
                direction=direction,
                stop_dist=100,
                profit_dist=200
            )
            self._print_green(f"Position opened. Deal ID: {deal_id}")
        except Exception as e:
            self._print_red(f"Failed to open position: {e}")
            return

        self._print_blue("Waiting 5 seconds before closing...")
        time.sleep(5)

        self._print_blue("Closing position...")
        try:
            result = self.close_position_by_id(deal_id)
            self._print_green(f"Position closed: {result}")
        except Exception as e:
            self._print_red(f"Failed to close position: {e}")
