# capitalcom

A Python client for the [Capital.com](https://capital.com) REST and WebSocket API, for demo
and live accounts. It logs in and keeps the session alive for you, places and confirms trades,
reads markets, prices and history, and streams live quotes, with typed results, `Decimal`
numbers and typed errors.

## Install

```bash
pip install --pre capitalcom
```

`--pre` is needed while 2.0 is a release candidate; without it pip installs 1.0.4, which this
site does not describe.

Optional extras:

- `pip install --pre "capitalcom[streaming]"` for live prices over the WebSocket;
- `pip install --pre "capitalcom[encryption]"` to send the password encrypted at login.

Python 3.11 or newer.

## Where next

- [Migration from 1.x](guides/migration.md), if you use `CapitalClient` today.
- [API reference](reference/client.md), generated from the code.
- [Design decisions](adr/0001-record-architecture-decisions.md), the reasons behind the
  behaviour.
