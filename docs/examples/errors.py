"""Errors a trading bot handles, and what each one tells it to do next."""

import os
from decimal import Decimal

from capitalcom import (
    CapitalCom,
    CapitalComError,
    ConfirmationTimeoutError,
    DealRejectedError,
    Direction,
    Environment,
    OutcomeUnknownError,
    RateLimitError,
    SizeAdjustedError,
    ValidationError,
)


def main() -> None:
    with CapitalCom(
        os.environ["CAPITAL_API_KEY"],
        os.environ["CAPITAL_IDENTIFIER"],
        os.environ["CAPITAL_PASSWORD"],
        environment=Environment.DEMO,
    ) as cc:
        details = cc.markets.get("BTCUSD")

        # --8<-- [start:validation]
        try:
            # Smaller than the minimum: refused here, nothing reaches the server.
            cc.positions.open("BTCUSD", Direction.BUY, Decimal("0.00001"), instrument=details)
        except ValidationError as error:
            print(f"refused before sending: {error}")
        # --8<-- [end:validation]

        # --8<-- [start:deal]
        size = details.dealing_rules.min_deal_size.value
        try:
            opened = cc.positions.open("BTCUSD", Direction.BUY, size)
        except DealRejectedError as error:
            # The server answered: no deal was made, and sending again will not change that.
            print(f"rejected: {error.reason}")
        except SizeAdjustedError as error:
            # A deal was made, with another size: close it, or keep managing it.
            print(f"booked {error.confirmation.size} instead of {error.requested}")
            if error.confirmation.position_id is not None:
                cc.positions.close(error.confirmation.position_id)
        except (OutcomeUnknownError, ConfirmationTimeoutError):
            # Sent, but not confirmed either way: the deal may exist. Look before sending it
            # again. ConfirmationTimeoutError is not an OutcomeUnknownError; catch both here.
            print(f"the deal may exist; {len(cc.positions.list())} positions are open")
        except RateLimitError:
            print("too many requests; wait before the next one")
        except CapitalComError as error:
            print(f"failed: {error}")
        else:
            if opened.position_id is not None:
                cc.positions.close(opened.position_id)
        # --8<-- [end:deal]


if __name__ == "__main__":
    main()
