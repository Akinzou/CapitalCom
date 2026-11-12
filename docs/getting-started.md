# Getting started

This page takes you from installing the library to opening and closing a position on a demo
account, then shows what changes for a live account.

## Install

```bash
pip install --pre capitalcom
```

`--pre` is needed while 2.0 is a release candidate. Python 3.11 or newer is required.
Two extras add optional features:

- `capitalcom[streaming]` for live quotes and bars over the WebSocket, installed with
  `pip install --pre "capitalcom[streaming]"`;
- `capitalcom[encryption]` to send the password encrypted at login, installed with
  `pip install --pre "capitalcom[encryption]"`.

## Credentials

The client needs three values:

- the **API key**, which you create in the Capital.com platform settings;
- the **identifier**, the login (e-mail address) of the account the key belongs to;
- the **password**, which is the API key's custom password.

Keep them out of your code. The examples on this site read them from the environment
variables `CAPITAL_API_KEY`, `CAPITAL_IDENTIFIER` and `CAPITAL_PASSWORD`, so set those three
before running them.

The client keeps the key, the password and the session tokens out of its `repr` and masks
them in its log records ([Errors and reliability](guides/reliability.md#secrets-in-logs-and-errors)).

## Your first trade

This opens the smallest BTCUSD position the demo account allows and closes it again:

```python
--8<-- "docs/examples/quickstart.py"
```

Step by step:

1. `CapitalCom(...)` builds the client for `Environment.DEMO`. It does not log in yet.
2. `cc.markets.get("BTCUSD")` logs in and reads the market's details, including its
   dealing rules. The minimum deal size is a `Decimal`.
3. `cc.positions.open(...)` sends the order and waits for the server's confirmation.
   `opened.deal_status` and `opened.size` come from that confirmation.
4. `opened.position_id` is the id of the new position. It is `None` when the deal netted
   against a position that was already open, so the example checks it before closing.
5. `cc.positions.close(...)` closes the whole position and returns its confirmation.
6. Leaving the `with` block logs out.

The test suite runs this file, and the contract job runs it against the demo server. The
contract tests have met BTCUSD closed on demo around 22:00 UTC
([ADR 0010](adr/0010-trading.md)); run the example while the market is open.

## Going live

`Environment.DEMO` is the default. To trade on your live account, pass
`environment=Environment.LIVE`; the same calls then go to the live server.

!!! warning
    `Environment.LIVE` trades real money. Every order you place on it is a real trade on your
    account. Run every change on demo first, and read
    [Errors and reliability](guides/reliability.md) before you do: some failures leave you not
    knowing whether a trade was made, and the library will not resend it for you.

`cc.accounts.top_up(...)` works on demo only; on `Environment.LIVE` it raises
`ValidationError` without sending anything.

## Next steps

- [Sessions and accounts](guides/sessions.md): logging in, renewal, accounts and history.
- [Markets and prices](guides/markets.md): finding markets, dealing rules, price history.
- [Trading](guides/trading.md): stops, take-profits, confirmations and sizes.
- [Streaming](guides/streaming.md): live quotes and bars.
- [Errors and reliability](guides/reliability.md): what each error means for your trades.
