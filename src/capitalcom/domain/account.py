"""Session and account read models."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from capitalcom.domain.parsing import (
    as_mapping,
    optional_str,
    require_bool,
    require_decimal,
    require_list,
    require_mapping,
    require_str,
    to_int,
)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """The live session, from ``GET /api/v1/session``."""

    client_id: str
    account_id: str
    timezone_offset: Decimal
    locale: str
    currency: str
    stream_endpoint: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "SessionInfo":
        """Build the session info from the decoded JSON body."""
        return cls(
            client_id=require_str(payload, "clientId"),
            account_id=require_str(payload, "accountId"),
            # Decimal, not int: some zones are offset by half or three quarters of an hour.
            timezone_offset=require_decimal(payload, "timezoneOffset"),
            locale=require_str(payload, "locale"),
            currency=require_str(payload, "currency"),
            stream_endpoint=require_str(payload, "streamEndpoint"),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class Balance:
    """Money on an account, in the account currency."""

    balance: Decimal
    deposit: Decimal
    profit_loss: Decimal
    available: Decimal

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Balance":
        """Build the balance from its JSON object."""
        return cls(
            balance=require_decimal(payload, "balance"),
            deposit=require_decimal(payload, "deposit"),
            profit_loss=require_decimal(payload, "profitLoss"),
            available=require_decimal(payload, "available"),
        )


@dataclass(frozen=True, slots=True)
class Account:
    """One trading account of the client, from ``GET /api/v1/accounts``.

    ``account_type`` and ``status`` stay strings: Capital.com may add values, and a listing
    must not fail because one account has a type this version does not know.
    """

    account_id: str
    account_name: str
    account_type: str
    status: str
    currency: str
    preferred: bool
    balance: Balance
    symbol: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Account":
        """Build an account from its JSON object."""
        return cls(
            account_id=require_str(payload, "accountId"),
            account_name=require_str(payload, "accountName"),
            account_type=require_str(payload, "accountType"),
            status=require_str(payload, "status"),
            currency=require_str(payload, "currency"),
            preferred=require_bool(payload, "preferred"),
            balance=Balance.from_api(require_mapping(payload, "balance")),
            symbol=optional_str(payload, "symbol"),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class Leverage:
    """Leverage of one instrument class: the one in force and the ones allowed."""

    current: int
    available: tuple[int, ...]

    @classmethod
    def from_api(cls, payload: Mapping[str, Any], name: str) -> "Leverage":
        """Build the leverage of instrument class ``name``."""
        where = f"leverages.{name}"
        available = require_list(payload, "available")
        return cls(
            current=to_int(payload.get("current"), f"{where}.current"),
            available=tuple(to_int(v, f"{where}.available") for v in available),
        )


@dataclass(frozen=True, slots=True)
class AccountPreferences:
    """Hedging mode and per-class leverage, from ``GET /api/v1/accounts/preferences``.

    Leverages are keyed by the server's class names (``SHARES``, ``CURRENCIES``, ...) as
    strings, so a class added by Capital.com shows up instead of breaking the read.
    """

    hedging_mode: bool
    leverages: Mapping[str, Leverage]
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "AccountPreferences":
        """Build the preferences from the decoded JSON body."""
        leverages = require_mapping(payload, "leverages")
        return cls(
            hedging_mode=require_bool(payload, "hedgingMode"),
            leverages={
                name: Leverage.from_api(as_mapping(value, f"leverages.{name}"), name)
                for name, value in leverages.items()
            },
            raw=payload,
        )
