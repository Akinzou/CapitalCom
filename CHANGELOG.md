# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased] — 2.0.0

### Added

- **`CapitalCom`, the 2.x client** (`from capitalcom import CapitalCom`). It logs in lazily,
  renews the session before Capital.com's 10-minute idle timeout, and logs out on `close()` or
  at the end of a `with` block. This release exposes `cc.session.ping()` and
  `cc.session.logout()`; trading and market resources follow.
- **Typed errors.** Every error derives from `CapitalComError` (and from `Exception`).
  Server refusals are `ApiError` subclasses that carry `status` and `error_code`. A trade
  whose outcome is unknown after a timeout raises `OutcomeUnknownError` instead of being
  retried.
- **Safe transport.** Every request has connect and read timeouts. TLS verification cannot be
  switched off, redirects are not followed, and requests are throttled to Capital.com's
  published limits. `429` responses are retried with backoff and `Retry-After`.
- **Precise numbers.** Prices, sizes and amounts are `Decimal`, and timestamps are aware UTC
  `datetime` values.
- **Redacted logs.** The library logs under `capitalcom` with a `NullHandler`, and masks the
  API key, password and session tokens in its own log records.

### Changed

- **Licence.** 1.0.x carried conflicting licence metadata: the licence field and the README
  said CC BY-NC 4.0, and the package classifier said MIT. From 2.0.0 the terms are the
  PolyForm Noncommercial License 1.0.0 (`LICENSE`) plus the additional permission for personal
  trading in `LICENSE-ADDITIONAL-PERMISSION`. Commercial licences are available on request.
- **Python support.** Python 3.11 or newer is required. Python 3.8–3.10 are no longer
  supported.
- **Dependencies.** `requests>=2.32.4` is required.
