"""Markets and prices: search, read the dealing rules, fetch bars and sentiment."""

import os

from capitalcom import CapitalCom, Environment, Resolution


def main() -> None:
    with CapitalCom(
        os.environ["CAPITAL_API_KEY"],
        os.environ["CAPITAL_IDENTIFIER"],
        os.environ["CAPITAL_PASSWORD"],
        environment=Environment.DEMO,
    ) as cc:
        # --8<-- [start:search]
        for market in cc.markets.search("bitcoin")[:5]:
            print(f"{market.epic}: {market.instrument_name}, bid {market.bid} offer {market.offer}")
        # --8<-- [end:search]

        # --8<-- [start:details]
        details = cc.markets.get("BTCUSD")
        rules = details.dealing_rules
        print(f"status {details.snapshot.market_status}")
        print(f"size from {rules.min_deal_size.value} to {rules.max_deal_size.value}")
        print(f"in steps of {rules.min_size_increment.value}")
        # --8<-- [end:details]

        # --8<-- [start:prices]
        for bar in cc.prices.history("BTCUSD", Resolution.HOUR, limit=3):
            print(f"{bar.time:%Y-%m-%d %H:%M} close bid {bar.close.bid} ask {bar.close.ask}")
        # --8<-- [end:prices]

        # --8<-- [start:sentiment]
        sentiment = cc.sentiment.get("BTCUSD")
        print(f"{sentiment.long_percentage}% long, {sentiment.short_percentage}% short")
        # --8<-- [end:sentiment]


if __name__ == "__main__":
    main()
