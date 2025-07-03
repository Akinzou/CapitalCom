import requests
import time
import logging
import random

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
        self.login_session()

    def login_session(self):
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
            self.token_expiry = time.time() + 600
            colored_log("INFO", "Session opened successfully.")
        else:
            colored_log("ERROR", f"Login failed: {response.status_code} {response.text}")
            raise Exception(f"Login failed: {response.status_code} {response.text}")

    def _headers(self):
        return {
            'CST': self.cst,
            'X-SECURITY-TOKEN': self.security_token
        }

    def _request(self, method, path, **kwargs):
        """
        Make an authenticated API request.
        Handles token expiry (401) and rate limiting (429) with retry and fixed backoff.
        """
        max_retries = 10
        rate_limit_wait = 1.0  # wait time (in seconds) on 429

        for attempt in range(max_retries):
            if time.time() > self.token_expiry:
                colored_log("DEBUG", "Session expired. Renewing...")
                self.login_session()

            url = f"{self.base_url}{path}"
            headers = kwargs.pop('headers', {})
            headers.update(self._headers())

            response = self.session.request(method, url, headers=headers, **kwargs)

            # Retry once if unauthorized (session expired)
            if response.status_code == 401 and attempt == 0:
                colored_log("DEBUG", "Token invalid. Retrying request after re-authentication...")
                self.login_session()
                continue

            # Retry with fixed delay on rate limiting
            if response.status_code == 429:
                colored_log("WARNING",
                            f"Rate limited (429). Waiting {rate_limit_wait:.1f}s before retrying... ({attempt + 1}/{max_retries})")
                time.sleep(rate_limit_wait)
                continue

            return response

        raise Exception(f"Request failed after {max_retries} retries: {method} {path}")

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

    def lot_to_size(self, lot, lot_size):
        return lot * lot_size

    def pips_to_profit_distance(self, pips, pip_position):
        return pips * 10 ** (-pip_position) if pips else None

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

