# capitalcom

A Python client for the [Capital.com](https://capital.com) REST and WebSocket API, for demo
and live accounts. It logs in and keeps the session alive for you, places and confirms trades,
reads markets, prices and history, and streams live quotes, with typed results, `Decimal`
numbers and typed errors.

## Install

--8<-- "docs/snippets/install.md"

## Quick start

With the API key, your login and the key's password exported as `CAPITAL_API_KEY`,
`CAPITAL_IDENTIFIER` and `CAPITAL_PASSWORD`, this opens the smallest BTCUSD position on the
demo account and closes it again:

```python
--8<-- "docs/examples/quickstart.py"
```

It prints the deal status and the booked size, then the close status. The test suite runs
this exact file, and the contract job runs it against the demo server.

## Where next

- [Getting started](getting-started.md), a walk-through of the quick start and of going live.
- [Errors and reliability](guides/reliability.md), what each error means for an open trade.
- [Migration from 1.x](guides/migration.md), if you use `CapitalClient` today.
- [API reference](reference/client.md), generated from the code.
- [Design decisions](adr/0001-record-architecture-decisions.md), the reasons behind the
  behaviour.
