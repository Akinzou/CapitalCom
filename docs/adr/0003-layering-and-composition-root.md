# 3. Layering and composition root

- Status: accepted
- Date: 2026-11-11

## Context

The library follows Clean Architecture with ports and adapters. Ports exist only where code
crosses a process boundary: HTTP, WebSocket and the clock. The design listed the allowed
dependency directions as `api -> application -> domain` and `infrastructure -> application`,
but something has to construct the concrete adapters and hand them to the application services.

## Decision

Each module has a rank:

| Rank | Modules |
|---|---|
| 0 | `capitalcom.domain.*`: values, entities, pure rules |
| 1 | `capitalcom.application.*`: ports, `Result`, services |
| 2 | `capitalcom.infrastructure.*`: adapters (`requests`, system clock, later WebSocket) |
| 3 | `capitalcom.api.*`: public facade and **composition root** |
| 4 | `capitalcom` package root and the legacy `capitalcom.client` |

A module may import only modules of equal or lower rank. `api` is the composition root, so
`api -> infrastructure` is allowed; `application -> infrastructure` is not.

Ranks 0 and 1 must not import `requests`, `urllib3`, `cryptography`, `websocket`, `socket` or
`time`. Waiting and reading time go through the `Clock` port, so services can be tested with a
fake clock and no real sleeps.

`tests/architecture/test_layers.py` enforces these rules and fails on any import cycle. Imports
under `if TYPE_CHECKING:` count, because a type-only cycle still couples the modules.

## Consequences

- Swapping `requests` for another HTTP client touches only `infrastructure` and the composition
  root.
- An async API can be added later as new adapters and a new facade, reusing domain and
  application logic.
