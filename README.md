# CapitalCom 

A lightweight Python wrapper for the Capital.com REST API.
Supports demo and live accounts. Designed for algorithmic trading, market data exploration, and automated execution.

---

## Features

- Open and close market positions
- Query account/session info
- Search instruments and market data
- Supports automatic session renewal
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
    password="your_password",
    demo=True  # set to False for real account
)

# Open and close a test trade
client.test_trade()
```

---

## Methods overview

| Method | Description |
|--------|-------------|
| `open_forex_position(...)` | Open a market order on forex with SL/TP in pips |
| `get_open_positions()`     | Get all active positions |
| `close_position_by_id(deal_id)` | Close a position by its deal ID |
| `search_instrument(term)` | Search instruments by name |
| `list_all_instruments()`  | Recursively list all tradable markets |

---

## License

This project is licensed under the CC BY-NC 4.0 License.

---

## Notes

- Works with REST API only (not streaming).
- `requests` is the only dependency.
