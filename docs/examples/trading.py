"""Trading: a protected position, amended and closed, and a working order placed and cancelled."""

import os
from decimal import Decimal

from capitalcom import (
    CapitalCom,
    Direction,
    Environment,
    OrderType,
    SizeAdjustedError,
    StopLoss,
    TakeProfit,
)


def main() -> None:
    with CapitalCom(
        os.environ["CAPITAL_API_KEY"],
        os.environ["CAPITAL_IDENTIFIER"],
        os.environ["CAPITAL_PASSWORD"],
        environment=Environment.DEMO,
    ) as cc:
        details = cc.markets.get("BTCUSD")
        bid = details.snapshot.bid
        if bid is None:
            print("BTCUSD has no quote right now")
            return
        size = details.dealing_rules.min_deal_size.value
        tick = Decimal(1).scaleb(-details.snapshot.decimal_places_factor)

        # --8<-- [start:open]
        stop = StopLoss(distance=(bid * Decimal("0.05")).quantize(tick))
        profit = TakeProfit(distance=(bid * Decimal("0.10")).quantize(tick))
        try:
            # instrument= checks the size against the dealing rules before sending
            opened = cc.positions.open(
                "BTCUSD", Direction.BUY, size, stop=stop, profit=profit, instrument=details
            )
        except SizeAdjustedError as error:
            # The deal was booked, with the size the server chose.
            opened = error.confirmation
            print(f"booked {opened.size} instead of {error.requested}")
        print(f"open: {opened.deal_status}")
        # --8<-- [end:open]

        position_id = opened.position_id
        if position_id is None:
            print("the deal netted against an existing position; nothing new to manage")
            return

        # --8<-- [start:amend]
        # An amendment replaces all protection: pass the take-profit again to keep it.
        tighter = StopLoss(distance=(bid * Decimal("0.03")).quantize(tick))
        amended = cc.positions.amend(position_id, stop=tighter, profit=profit)
        print(f"amend: {amended.deal_status}")
        # --8<-- [end:amend]

        # --8<-- [start:close]
        closed = cc.positions.close(position_id)
        print(f"close: {closed.deal_status}")
        # --8<-- [end:close]

        # --8<-- [start:order]
        level = (bid * Decimal("0.5")).quantize(tick)  # far below the market: it will not fill
        order = cc.orders.create("BTCUSD", Direction.BUY, size, level=level, type=OrderType.LIMIT)
        print(f"order: {order.deal_status}")
        if order.deal_id is not None:
            cancelled = cc.orders.cancel(order.deal_id)
            print(f"cancel: {cancelled.deal_status}")
        # --8<-- [end:order]


if __name__ == "__main__":
    main()
