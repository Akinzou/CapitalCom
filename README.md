# CapitalCom  [![CI](https://github.com/Akinzou/CapitalCom/actions/workflows/ci.yml/badge.svg)](https://github.com/Akinzou/CapitalCom/actions/workflows/ci.yml) ![PyPI](https://img.shields.io/pypi/v/capitalcom) ![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white) ![License](https://img.shields.io/badge/license-PolyForm_Noncommercial_1.0.0-lightgrey.svg) [![PyPI Downloads](https://static.pepy.tech/badge/capitalcom)](https://pepy.tech/projects/capitalcom)
[![Discord](https://img.shields.io/badge/Join_us_on-Discord-5865F2?logo=discord&logoColor=white&style=for-the-badge)](https://discord.gg/BARYa55KS8)

A Python client for the [Capital.com](https://capital.com) REST and WebSocket API, for demo
and live accounts. It logs in and keeps the session alive, places trades and waits for their
confirmation, reads markets, prices and history, and streams live quotes. Results are typed
objects, numbers are `Decimal`, and failures are typed exceptions.

**Documentation: [akinzou.github.io/CapitalCom](https://akinzou.github.io/CapitalCom/)**

## Install

```bash
pip install capitalcom
```

Optional extras: `capitalcom[streaming]` for live prices over the WebSocket, and
`capitalcom[encryption]` to send the password encrypted. Python 3.11 or newer; on an older Python, pip installs 1.0.4.

## Quick start

Create an API key in the Capital.com platform settings, export it with your login and the
key's password as `CAPITAL_API_KEY`, `CAPITAL_IDENTIFIER` and `CAPITAL_PASSWORD`, then run:

```python
"""Open the smallest BTCUSD position on the demo account, then close it."""

import os

from capitalcom import CapitalCom, Direction, Environment


def main() -> None:
    with CapitalCom(
        os.environ["CAPITAL_API_KEY"],
        os.environ["CAPITAL_IDENTIFIER"],
        os.environ["CAPITAL_PASSWORD"],
        environment=Environment.DEMO,
    ) as cc:
        market = cc.markets.get("BTCUSD")
        size = market.dealing_rules.min_deal_size.value  # a Decimal, e.g. 0.0001

        opened = cc.positions.open("BTCUSD", Direction.BUY, size)
        print(f"open: {opened.deal_status}, size {opened.size}")

        if opened.position_id is None:
            print("the deal netted against an existing position; nothing new to close")
            return
        closed = cc.positions.close(opened.position_id)
        print(f"close: {closed.deal_status}")


if __name__ == "__main__":
    main()
```

The output is the deal status and the booked size, then the close status. See
[Getting started](https://akinzou.github.io/CapitalCom/getting-started/) for the walk-through.

## Going live

The example trades on the demo account. `Environment.LIVE` sends the same calls to your real
account, with real money: read [Errors and reliability](https://akinzou.github.io/CapitalCom/guides/reliability/) first,
and try every change on demo.

## Coming from 1.x

`CapitalClient` keeps working in 2.x, with a `DeprecationWarning`, and will be removed no earlier than 3.0.
To stay on 1.x for now, pin `capitalcom<2` in your requirements.
The [migration guide](https://akinzou.github.io/CapitalCom/guides/migration/) maps each 1.x call to its 2.x equivalent.

## License

This project is licensed under the [PolyForm Noncommercial License 1.0.0](https://github.com/Akinzou/CapitalCom/blob/master/LICENSE).

In addition, any individual may use it to trade their own personal Capital.com accounts,
demo or live, including for profit. See [LICENSE-ADDITIONAL-PERMISSION](https://github.com/Akinzou/CapitalCom/blob/master/LICENSE-ADDITIONAL-PERMISSION)
for the exact terms. Commercial licences are available on request: root@yelon.dev or
wiktorjn@gmail.com.
