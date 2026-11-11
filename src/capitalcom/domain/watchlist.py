"""Watchlists and the outcome of creating one."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from capitalcom.domain.errors import ApiError, ValidationError
from capitalcom.domain.parsing import require_bool, require_str

# Documented bounds of a watchlist name; the server answers a longer one with a 400.
MAX_NAME_LENGTH = 20

# A partial create still makes the list, so it is reported as a flag rather than raised:
# an exception would lose the id of a watchlist that already exists.
_CREATED = {"SUCCESS": True, "SUCCESS_NOT_ALL_INSTRUMENTS_ADDED": False}


def check_name(name: object) -> str:
    """Return ``name`` when it is a string of 1..20 characters."""
    if not isinstance(name, str) or not 1 <= len(name) <= MAX_NAME_LENGTH:
        raise ValidationError(f"name must be a string of 1..{MAX_NAME_LENGTH} characters")
    return name


@dataclass(frozen=True, slots=True)
class Watchlist:
    """One watchlist, from ``GET /watchlists``."""

    watchlist_id: str
    name: str
    editable: bool
    deleteable: bool
    default_system: bool
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Watchlist":
        """Build a watchlist from one item of ``watchlists``."""
        return cls(
            watchlist_id=require_str(payload, "id"),
            name=require_str(payload, "name"),
            editable=require_bool(payload, "editable"),
            deleteable=require_bool(payload, "deleteable"),
            default_system=require_bool(payload, "defaultSystemWatchlist"),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class WatchlistCreation:
    """A created watchlist; ``all_epics_added`` is False when the server left epics out."""

    watchlist_id: str
    all_epics_added: bool

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "WatchlistCreation":
        """Build the outcome; a status other than the two documented successes raises."""
        status = payload.get("status")
        if status not in _CREATED:
            raise ApiError(200, None, f"watchlist not created: {dict(payload)!r}")
        return cls(require_str(payload, "watchlistId"), _CREATED[status])
