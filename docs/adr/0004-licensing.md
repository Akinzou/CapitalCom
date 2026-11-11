# 4. Licensing

- Status: accepted
- Date: 2026-11-11

## Context

Releases 1.0.x carried conflicting licence metadata: the licence field and the README said
CC BY-NC 4.0, while the package classifier said MIT. Creative Commons advises against its
licences for software, and the MIT classifier contradicted the non-commercial intent.

The owner's intent: individuals may use the library freely, including to trade their own
accounts for profit; commercial use (businesses, services, products) needs a separate licence.

## Decision

- From 2.0.0 the software is licensed under the **PolyForm Noncommercial License 1.0.0**, a
  licence written for software, stored verbatim in `LICENSE` with the required copyright notice.
- `LICENSE-ADDITIONAL-PERMISSION` grants every natural person the right to use the software to
  trade their own personal accounts, demo or live, including for profit. It excludes use for
  others, inside organizations, and in distributed or hosted products.
- Commercial licences are offered by the owner on request.
- Packaging metadata follows PEP 639: `license = "LicenseRef-PolyForm-Noncommercial-1.0.0"` and
  `license-files`. No `License ::` classifier is set, because PEP 639 forbids combining them.
- The CHANGELOG states the 1.0.x metadata conflict as a fact and makes no claim about which
  licence applied to those releases.

## Consequences

- The package is source-available, not OSI open source. Some organizations' policies will
  block it; that matches the owner's intent.
- The owner is advised to have a lawyer review the additional permission and the commercial
  licence terms.
