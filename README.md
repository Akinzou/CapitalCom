# CapitalCom  [![PyPI Publish](https://github.com/Akinzou/CapitalCom/actions/workflows/python-publish.yml/badge.svg)](https://github.com/Akinzou/CapitalCom/actions/workflows/python-publish.yml) ![PyPI](https://img.shields.io/pypi/v/capitalcom) ![Python](https://img.shields.io/badge/python-3.8%2B-blue?logo=python&logoColor=white) ![License](https://img.shields.io/badge/license-CC_BY--NC_4.0-lightgrey.svg) 



A lightweight Python wrapper for the Capital.com REST API.
Supports demo and live accounts. Designed for algorithmic trading, market data exploration, and automated execution.

---

## Features

- Open and close market positions
- Lot-based forex trading with SL/TP (in pips)
- Automatic session token renewal
- View and manage demo account balance
- List and search tradable instruments
- Colored CLI feedback (green/red/blue)

---

##  Installation

```bash
pip install capitalcom
```

---

## Example usage

```python
from capitalcom_client import CapitalClient

client = CapitalClient(
    api_key="your_api_key",
    login="your_email",
    password="your_api_password",
    demo=True  # Set to False for live account
)

# List your accounts
client.list_accounts()

# Check balance
balance = client.get_balance()
print("Current balance:", balance)

# Open and close a test trade
client.test_trade()

# Add demo funds
client.top_up_demo(5000)

)

# Open and close a test trade
client.test_trade()
```

---

## Available Methods

| Method | Description |
|--------|-------------|
| `open_forex_position(epic, size, direction, stop_dist=None, profit_dist=None)` | Open forex trade (lot-based) |
| `open_raw_position(epic, size, direction, ...)` | Open position with raw size |
| `close_position_by_id(deal_id, size=None)` | Close full or partial position |
| `get_open_positions()` | List all open positions |
| `search_instrument(term)` | Search instruments via market navigation |
| `search_markets(term)` | Search instruments via `/markets` endpoint |
| `list_all_instruments()` | Recursively list all tradable instruments |
| `get_session_info()` | View session, `accountId`, `clientId` |
| `get_balance(account_id=None, raw=False)` | Fetch current account balance |
| `list_accounts()` | List all your accounts and IDs |
| `top_up_demo(amount)` | Add funds to demo account (up to 100K) |
| `test_trade()` | Execute a small test trade (0.001 lot EUR/USD) |


---

## License

This project is licensed under the CC BY-NC 4.0 License.

---

## Notes

- Works with REST API only (not streaming).
- `requests` is the only dependency.
