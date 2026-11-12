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
