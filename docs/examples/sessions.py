"""Sessions and accounts: log in lazily, read the accounts, read the history."""

import os
from datetime import timedelta

from capitalcom import CapitalCom, Environment


def main() -> None:
    # --8<-- [start:client]
    cc = CapitalCom(
        os.environ["CAPITAL_API_KEY"],
        os.environ["CAPITAL_IDENTIFIER"],
        os.environ["CAPITAL_PASSWORD"],
        environment=Environment.DEMO,
    )
    try:
        info = cc.session.info()  # the first call logs in
        print(f"logged in, account currency {info.currency}")
    finally:
        cc.close()  # logs out; `with CapitalCom(...) as cc:` does the same
    # --8<-- [end:client]

    with CapitalCom(
        os.environ["CAPITAL_API_KEY"],
        os.environ["CAPITAL_IDENTIFIER"],
        os.environ["CAPITAL_PASSWORD"],
        environment=Environment.DEMO,
    ) as cc:
        # --8<-- [start:accounts]
        for account in cc.accounts.list():
            # account.balance.available is what may still be committed to new deals
            marker = " (preferred)" if account.preferred else ""
            print(f"{account.account_name}, {account.currency}{marker}")
        # --8<-- [end:accounts]

        # --8<-- [start:history]
        for activity in cc.history.activity(last_period=timedelta(hours=24)):
            print(f"{activity.date:%Y-%m-%d %H:%M} {activity.type} {activity.status}")
        # --8<-- [end:history]


if __name__ == "__main__":
    main()
